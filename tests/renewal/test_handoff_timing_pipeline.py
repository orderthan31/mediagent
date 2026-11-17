"""Actual boundaries with offline seams; no database, network or model execution."""
import hashlib
import io
import json
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pika
import pytest

from video_service.canonical import digest
from video_service.content_store import ContentStore
from video_service.handoff_timing import handoff_context, handoff_span, timing_sink
from video_service.object_store import ObjectIntegrityError, S3ContentStore
from video_service.rabbitmq_transport import BrokerConfig, BrokerError, InvalidMessage, RabbitClient, envelope
from mideagent_orchestrator.controller import BrokerController

OWNER = "a" * 32
JOB = "b" * 32
ATTEMPT = "c" * 32


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline test attempted network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def command():
    return {"protocol_version": 1, "run_id": JOB, "attempt_id": ATTEMPT,
            "generation": 1, "agent": {"id": "analyze", "revision": "1"},
            "inputs": {"video": {"storage_key": "blobs/" + "d" * 64,
                       "sha256": "d" * 64, "bytes": 1, "type": "video"}}, "options": {}}


def delivery():
    cmd = command()
    result = {key: cmd[key] for key in ("protocol_version", "run_id", "attempt_id", "generation", "agent")}
    result.update(request_sha256=digest(cmd), status="failed", outputs={},
                  transport="s3_subprocess", error={"code": "tool_failed", "retryable": False})
    return envelope(OWNER, cmd, result)


class Peer:
    def __init__(self, raw):
        self.raw, self.gets, self.bodies = raw, [], []

    def get_object(self, **kw):
        self.gets.append(kw)
        body = io.BytesIO(self.raw)
        self.bodies.append(body)
        return {"Body": body, "ContentLength": len(self.raw)}


def test_real_s3_path_repeats_get_hash_materialize_and_rejects_corruption(tmp_path):
    raw = b"SECRET-MEDIA" * 220000
    sha = hashlib.sha256(raw).hexdigest()
    peer = Peer(raw)
    store = S3ContentStore(peer, "private-bucket", tmp_path, prefix="PRIVATE-PREFIX")
    ref = ContentStore.put(store, OWNER, [raw], "video")
    records = []
    with timing_sink(records.append), handoff_context(job_id=JOB):
        for _ in range(2):
            assert store.path(OWNER, ref).read_bytes() == raw
        peer.raw = b"X" * len(raw)
        with pytest.raises(ObjectIntegrityError, match="integrity"):
            store.path(OWNER, ref)
    assert len(peer.gets) == 3 and all(body.closed for body in peer.bodies)
    downloads = [r for r in records if r["stage"] == "object_download_hash_write"]
    assert len(downloads) == 3
    assert all(r["bytes"] == len(raw) and r["hash_ms"] >= 0 and r["write_ms"] >= 0 for r in downloads)
    assert sum(r["stage"] == "object_get" for r in records) == 3
    assert sum(r["stage"] == "object_materialize" for r in records) == 2
    assert len(records) == 11  # fixed records per object, never per stream block
    assert records[-1]["outcome"] == "error"
    assert all(r["job_id"] == JOB for r in records)
    text = json.dumps(records)
    for forbidden in ("SECRET-MEDIA", "PRIVATE-PREFIX", "private-bucket", "blobs/", str(tmp_path)):
        assert forbidden not in text
    assert sha in text


def test_controller_decode_accept_dispatch_order_and_validation(monkeypatch):
    events, records = [], []
    runtime = SimpleNamespace(store=SimpleNamespace(storage_kind="s3"), fleet=None)
    def accept(*args):
        events.append("accept")
        with handoff_span("result_accept"):
            pass
    runtime.accept = accept
    controller = BrokerController(runtime, lambda: None)
    def dispatch(owner, job):
        assert (owner, job) == (OWNER, JOB)
        events.append("dispatch")
        with handoff_span("dispatch"):
            pass
    monkeypatch.setattr(controller, "dispatch", dispatch)
    with timing_sink(records.append):
        assert controller.receive(delivery()) is None
        with pytest.raises(InvalidMessage):
            controller.receive(replace(delivery(), body=b"SECRET-INVALID"))
        with handoff_span("dispatch"):
            pass
    assert events == ["accept", "dispatch"]
    bound = [r for r in records if r.get("job_id") == JOB]
    assert [r["stage"] for r in bound] == ["result_accept", "dispatch"]
    assert all(r["attempt_id"] == ATTEMPT for r in bound)
    assert "job_id" not in records[-1]
    assert "SECRET-INVALID" not in json.dumps(records)
    failure = ValueError("SECRET-ACCEPT")
    def fail(*args):
        raise failure
    runtime.accept = fail
    with pytest.raises(ValueError) as caught:
        controller.receive(delivery())
    assert caught.value is failure
    assert events == ["accept", "dispatch"]


def test_actual_dispatch_loop_keeps_claim_publish_get_counts(monkeypatch):
    from mideagent_orchestrator.agent_pool import AgentPool
    monkeypatch.setattr(AgentPool, "blocked", lambda *args: False)
    calls = []
    class Runtime:
        store = SimpleNamespace(storage_kind="s3")
        fleet = None
        database = None
        step = 0
        def get(self, *args):
            calls.append("get")
            return {"status": "running", "snapshot": {"definition": {"nodes": [1, 2]}},
                    "runs": [] if not self.step else [{"id": ATTEMPT, "status": "running"}]}
        def claim_next(self, *args):
            calls.append("claim")
            self.step += 1
    controller = BrokerController(Runtime(), lambda: None)
    monkeypatch.setattr(controller, "publish_exact", lambda *args: calls.append("publish"))
    records = []
    with timing_sink(records.append):
        state = controller._dispatch_exact(OWNER, JOB)
    assert state["runs"][0]["id"] == ATTEMPT
    assert calls == ["get", "claim", "get", "publish", "get"]
    assert [r["stage"] for r in records] == ["dispatch"]


class Channel:
    def __init__(self, stop, events):
        self.stop, self.events, self.is_open = stop, events, True
    def confirm_delivery(self):
        self.events.append("confirm_mode")
    def queue_declare(self, **kwargs):
        self.events.append("passive")
        assert kwargs["passive"] is True
    def basic_qos(self, **kwargs):
        assert kwargs == {"prefetch_count": 1, "global_qos": False}
    def basic_consume(self, **kwargs):
        assert kwargs["auto_ack"] is False
        self.callback = kwargs["on_message_callback"]
        return "tag"
    def basic_cancel(self, tag):
        self.events.append("cancel")
    def basic_publish(self, **kwargs):
        self.events.append("publish")
        assert kwargs["mandatory"] is True
    def basic_ack(self, **kwargs):
        self.events.append("ack")
        self.stop.set()
    def basic_nack(self, **kwargs):
        self.events.append("nack")
        assert kwargs["requeue"] is False
        self.stop.set()


class Connection:
    is_open = True
    def __init__(self, channel, incoming=None):
        self.c, self.incoming = channel, incoming
    def channel(self):
        return self.c
    def process_data_events(self, **kwargs):
        if self.incoming is not None:
            d, self.incoming = self.incoming, None
            self.c.callback(self.c, SimpleNamespace(delivery_tag=1),
                pika.BasicProperties(type=d.message_type, message_id=d.message_id,
                    correlation_id=d.correlation_id, content_type=d.content_type,
                    content_encoding=d.content_encoding), d.body)
        time.sleep(0.001)
    def close(self):
        self.is_open = False
        self.c.events.append("close")


@pytest.mark.parametrize("invalid", [False, True])
def test_real_mq_callback_before_ack_and_invalid_nack(invalid, capsys):
    events, stop = [], threading.Event()
    channel = Channel(stop, events)
    client = RabbitClient(BrokerConfig("isolated.test", "UNUSED", True),
                          Connection(channel, delivery()), pika)
    def handler(value):
        events.append("handler")
        if invalid:
            raise InvalidMessage("SECRET")
        events.append("adopt_dispatch_done")
        return None
    client.serve("result", handler, stop)
    assert events.index("handler") < events.index("nack" if invalid else "ack")
    assert events.count("nack" if invalid else "ack") == 1
    if not invalid:
        assert events.index("adopt_dispatch_done") < events.index("ack")
    records = [json.loads(s) for s in capsys.readouterr().err.splitlines()]
    assert [r["stage"] for r in records] == ["mq_callback"]
    assert records[0]["outcome"] == ("error" if invalid else "ok")
    assert "SECRET" not in json.dumps(records)


def test_real_connect_publish_close_no_reuse_and_sink_failure(monkeypatch):
    events, records = [], []
    channel = Channel(threading.Event(), events)
    def connect(params):
        events.append("connect")
        return Connection(channel)
    monkeypatch.setattr(pika, "BlockingConnection", connect)
    config = BrokerConfig("isolated.test", "FIXTURE_URL", True)
    env = {"FIXTURE_URL": "amqp://fixture:SECRET@127.0.0.1/fixture"}
    with timing_sink(records.append):
        for _ in range(2):
            with RabbitClient.connect(config, environ=env) as client:
                assert client.publish(envelope(OWNER, command())) is True
    assert events == ["connect", "confirm_mode", "publish", "close"] * 2
    assert [r["stage"] for r in records] == ["mq_connect", "mq_publish_confirm"] * 2
    assert "SECRET" not in json.dumps(records)
    def fail(record):
        raise RuntimeError("SECRET")
    with timing_sink(fail), RabbitClient.connect(config, environ=env) as client:
        assert client.publish(envelope(OWNER, command())) is True


def test_actual_execution_import_and_preflight_boundaries(tmp_path):
    from mideagent_orchestrator.execution import Execution
    raw = b'{"format":"fixture"}'
    peer = Peer(raw)
    store = S3ContentStore(peer, "private-bucket", tmp_path, prefix="private")
    ref = ContentStore.put(store, OWNER, [raw], "media_metadata")
    runtime = object.__new__(Execution)
    runtime.store = store
    @contextmanager
    def connection():
        yield object()
    runtime.database = SimpleNamespace(connection=connection)
    runtime._job = lambda *args: {"snapshot": {}}
    records = []
    with timing_sink(records.append):
        assert runtime._preflight_cpu_inputs(OWNER, JOB) is None
        outputs = {"metadata": ref}
        result = runtime._import_outputs(OWNER, command(), {"transport": "s3_subprocess", "outputs": outputs})
        assert result is outputs
    assert len(peer.gets) == 1
    assert records[0]["stage"] == "preflight"
    assert records[-1]["stage"] == "result_import"


def test_model_delivery_validated_scope_adoption_and_settlement_order():
    from mideagent_orchestrator.model_delivery import RoleResultDeliveries
    events, records = [], []
    packet = {"version": 1, "role": "translation", "task_id": "e" * 32,
              "request_sha256": "f" * 64, "status": "completed", "output_owner": OWNER,
              "result_ref": {"storage_key": "blobs/" + "d" * 64,
                             "sha256": "d" * 64, "bytes": 1, "type": "transcript"}}
    class DB:
        @contextmanager
        def connection(self):
            events.append("begin")
            yield self
            events.append("commit")
        def execute(self, sql, params=None):
            if "SELECT * FROM model_role_tasks" in sql:
                self.row = {"envelope_sha256": packet["request_sha256"], "owner_id": OWNER,
                            "envelope": {"role": "translation"}, "job_id": JOB,
                            "attempt_id": ATTEMPT, "generation": 1}
            elif "pg_try_advisory_lock" in sql:
                self.row = {"ok": True}
            elif "SELECT * FROM model_role_result_deliveries" in sql:
                self.row = None if "insert" not in events else {"attempts": 0}
            elif "INSERT INTO" in sql:
                events.append("insert")
            elif "state='receiving'" in sql:
                events.append("budget_increment")
            elif "state='settled'" in sql:
                events.append("settled")
            return self
        def fetchone(self):
            return self.row
        def commit(self):
            events.append("explicit_commit")
        def rollback(self):
            events.append("rollback")
    coordinator = SimpleNamespace(
        runtime=SimpleNamespace(database=DB()), factory=SimpleNamespace(),
        roles=SimpleNamespace(receive=lambda packet: events.append("adopt")),
        _dispatch_after_result=lambda packet: events.append("dispatch"))
    with timing_sink(records.append):
        assert RoleResultDeliveries(coordinator).receive(packet) is None
    assert events.count("budget_increment") == events.count("adopt") == events.count("dispatch") == 1
    assert events.index("budget_increment") < events.index("adopt") < events.index("dispatch") < events.index("settled")
    adoption = next(r for r in records if r["stage"] == "model_adoption")
    assert (adoption["job_id"], adoption["attempt_id"], adoption["task_id"]) == (JOB, ATTEMPT, packet["task_id"])
    assert records[-1]["stage"] == "model_result_callback"


def test_durable_queued_publish_fast_path_calls_once(monkeypatch):
    from video_service.durable_transport import DurableTransport
    from video_service.postgres.dispatch_queue import DispatchQueue
    calls, records = [], []
    def publish(self, owner, job_id, message_id, send):
        calls.append((owner, job_id, message_id))
        return send(message_id, "fixed", b"SECRET")
    monkeypatch.setattr(DispatchQueue, "publish_exact", publish)
    runtime = SimpleNamespace(database=None)
    sends = []
    def send(*args):
        sends.append(args)
        return True
    with timing_sink(records.append):
        assert DurableTransport(runtime).publish_exact(OWNER, JOB, ATTEMPT, send) is True
    assert calls == [(OWNER, JOB, ATTEMPT)] and len(sends) == 1
    assert records[0]["stage"] == "outbox_publish" and "SECRET" not in json.dumps(records)


def test_accept_exception_identity_and_single_preflight():
    from mideagent_orchestrator.execution import Execution
    runtime = object.__new__(Execution)
    failure, calls, records = RuntimeError("SECRET"), [], []
    def preflight(*args):
        calls.append(args)
        raise failure
    runtime._preflight_cpu_inputs = preflight
    with timing_sink(records.append), pytest.raises(RuntimeError) as caught:
        runtime.accept(OWNER, command(), {})
    assert caught.value is failure and len(calls) == 1
    assert records[0]["stage"] == "result_accept" and records[0]["outcome"] == "error"
    assert "SECRET" not in json.dumps(records)


def test_actual_controller_cross_job_dispatch_does_not_inherit_source_attempt(monkeypatch):
    """Exercise receive→dispatch→advance_queue→actual _dispatch_exact, not just the helper."""
    from mideagent_orchestrator.agent_pool import AgentPool

    destination = "d" * 32
    destination_attempt = "e" * 32
    source_claim = "f" * 32
    calls, records = [], []
    monkeypatch.setattr(AgentPool, "blocked", lambda *args: False)

    class Runtime:
        store = SimpleNamespace(storage_kind="s3")
        fleet = None
        database = None
        destination_started = False

        def accept(self, owner, cmd, result):
            assert owner == OWNER and cmd["run_id"] == JOB
            calls.append(("accept", JOB))

        def get(self, owner, identity):
            assert owner == OWNER and identity in {JOB, destination}
            calls.append(("get", identity))
            if identity == JOB:
                return {"status": "failed", "snapshot": {"definition": {"nodes": [1]}},
                        "runs": [{"id": ATTEMPT, "status": "failed"}]}
            return {"status": "running", "snapshot": {"definition": {"nodes": [1]}},
                    "runs": ([{"id": destination_attempt, "status": "running"}]
                             if self.destination_started else [])}

        def claim_next(self, owner, identity):
            assert owner == OWNER
            calls.append(("claim", identity))
            with handoff_span("claim"):
                if identity == destination:
                    self.destination_started = True

    controller = BrokerController(Runtime(), lambda: None)
    monkeypatch.setattr(controller, "publish_exact",
                        lambda owner, identity, attempt: calls.append(("publish", identity, attempt)))
    monkeypatch.setattr(controller, "advance_queue",
                        lambda owner: controller._dispatch_exact(owner, destination))

    with timing_sink(records.append), handoff_context(
        root=True, job_id=JOB, attempt_id=ATTEMPT, generation=1, claim_id=source_claim
    ):
        controller.receive(delivery())
        with handoff_span("preflight"):
            pass

    destination_dispatches = [r for r in records
                              if r["stage"] == "dispatch" and r.get("job_id") == destination]
    assert len(destination_dispatches) == 1, records
    target = destination_dispatches[0]
    assert not {"attempt_id", "generation", "claim_id"} & target.keys()
    child_claim = next(r for r in records
                       if r["stage"] == "claim" and r.get("job_id") == destination)
    assert child_claim["parent_span_id"] == target["span_id"]
    assert child_claim["trace_id"] == target["trace_id"]
    assert not {"attempt_id", "generation", "claim_id"} & child_claim.keys()
    assert calls.count(("publish", destination, destination_attempt)) == 1
    restored = records[-1]
    assert (restored["job_id"], restored["attempt_id"], restored["generation"], restored["claim_id"]) == (
        JOB, ATTEMPT, 1, source_claim
    )
