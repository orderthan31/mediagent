import json
import signal
import threading
from types import SimpleNamespace

import pytest
from test_independent_transcription_agent import audio, request
from video_service.content_store import ContentStore
from video_service.cpu_agents import canonical
from video_service.object_store import ObjectIntegrityError, ObjectStoreError


class FakeChannel:
    def __init__(self, messages):
        self.messages = list(messages)
        self.callbacks = {}
        self.acks = []
        self.nacks = []
        self.results = []
        self.is_open = True
        self.stop = None
        self.confirm_failure = False

    def confirm_delivery(self):
        pass

    def queue_declare(self, **kwargs):
        pass

    def basic_qos(self, **kwargs):
        pass

    def basic_consume(self, queue, on_message_callback, **kwargs):
        self.callbacks[queue] = on_message_callback
        return queue

    def basic_cancel(self, tag):
        pass

    def basic_publish(self, **kwargs):
        if self.confirm_failure:
            raise OSError("controlled unconfirmed publish")
        self.results.append(kwargs)

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)
        if delivery_tag == 100 and self.stop:
            self.stop()

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))
        if delivery_tag == 100 and self.stop:
            self.stop()


class FakeConnection:
    def __init__(self, channel):
        self.ch = channel
        self.is_open = True

    def channel(self):
        return self.ch

    def close(self):
        self.is_open = False
        self.ch.is_open = False

    def process_data_events(self, time_limit):
        if self.ch.messages:
            kind, tag, body = self.ch.messages.pop(0)
            queue = (
                "test.transcription."
                + ("cancel" if kind == "cancel" else "inbox")
                + ".v1"
            )
            self.ch.callbacks[queue](
                self.ch,
                SimpleNamespace(delivery_tag=tag),
                SimpleNamespace(type="mideagent.model." + kind + ".v1"),
                body,
            )
        else:
            threading.Event().wait(0.001)


def fixture_case(tmp_path, monkeypatch, *, phase=None, messages=None):
    import mideagent_models.cli as cli
    import pika
    import video_service.object_store as stores
    import video_service.rabbitmq_transport as broker

    for folder in ["inputs", "outputs"]:
        (tmp_path / folder).mkdir()
    base_inputs = ContentStore(tmp_path / "inputs")
    base_outputs = ContentStore(tmp_path / "outputs")
    wav = audio(tmp_path / "a.wav", seconds=1)
    owner = "a" * 32
    ref = base_inputs.put(owner, [wav.read_bytes()], "audio")
    packet = request(wav, max_calls=1)
    packet["timeline"] = [
        {"packed_start": 0, "packed_end": 1, "source_start": 10, "source_end": 11}
    ]
    envelope = {
        "version": 1,
        "role": "transcription",
        "task": packet,
        "source": {"owner": owner, "reference": ref},
        "output_owner": owner,
    }
    calls = []
    faults = []

    class Inputs:
        def path(self, *args):
            if phase == "input_integrity":
                raise ObjectIntegrityError("Remote content integrity mismatch")
            if phase == "input_get" and not faults:
                faults.append(phase)
                raise ObjectStoreError("Object unavailable or transfer failed")
            return base_inputs.path(*args)

    class Outputs:
        def put(self, *args, **kwargs):
            if phase == "output_integrity":
                raise ObjectIntegrityError("Remote content integrity mismatch")
            if phase == "output_permanent":
                raise ObjectStoreError("Object write failed; outcome may be unknown")
            if phase == "output_put" and not faults:
                faults.append(phase)
                raise ObjectStoreError("Object write failed; outcome may be unknown")
            value = base_outputs.put(*args, **kwargs)
            if phase == "verification_get" and not faults:
                faults.append(phase)
                raise ObjectStoreError("Object unavailable or transfer failed")
            return value

    inputs, outputs = Inputs(), Outputs()
    ch = FakeChannel(
        messages if messages is not None else [("command", 100, canonical(envelope))]
    )
    conn = FakeConnection(ch)
    ch.connection = conn
    monkeypatch.setattr(pika, "BlockingConnection", lambda *_: conn)
    monkeypatch.setattr(broker.BrokerConfig, "parameters", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        stores,
        "from_config",
        lambda cfg: inputs if cfg["purpose"] == "input" else outputs,
    )
    monkeypatch.setattr(
        cli, "ScopedSpeechTool", lambda cfg: lambda *_: calls.append(1) or []
    )

    def register(sig, handler):
        if sig == signal.SIGTERM:
            ch.stop = lambda: handler(None, None)

    monkeypatch.setattr(signal, "signal", register)
    config = {
        "role": "transcription",
        "state_root": str(tmp_path / "state"),
        "task_slots": 1,
        "chunk_concurrency": 1,
        "tool_mode": "controlled_inprocess",
        "broker": {"namespace": "test", "url_env": "IGNORED"},
        "input_store": {"purpose": "input", "cache_root": str(tmp_path / "inputs")},
        "output_store": {"purpose": "output", "cache_root": str(tmp_path / "outputs")},
    }
    return config, ch, calls, envelope, base_outputs


@pytest.mark.parametrize("phase", ["input_get", "output_put", "verification_get"])
def test_artifact_transport_failure_recovers_without_recalling_completed_model(
    tmp_path, monkeypatch, phase
):
    from mideagent_models.broker import consume

    config, ch, calls, envelope, outputs = fixture_case(
        tmp_path, monkeypatch, phase=phase
    )
    consume(config, once=True)
    assert ch.acks == [100] and ch.nacks == []
    assert len(calls) == 1 and len(ch.results) == 1
    result = json.loads(ch.results[0]["body"])
    payload = json.loads(
        outputs.path(envelope["output_owner"], result["result_ref"]).read_bytes()
    )
    assert (
        payload["result"]["status"] == "completed"
        and "projection_trace" in payload["result"]
    )
    import sqlite3

    with sqlite3.connect(tmp_path / "state" / "role-state.sqlite") as c:
        frozen = c.execute("SELECT result FROM tasks").fetchone()[0]
    assert payload["result"] == json.loads(frozen)


def test_exhausted_artifact_retry_is_durable_held_without_reject_or_model_recall(
    tmp_path, monkeypatch
):
    import sqlite3

    from mideagent_models.broker import DeliveryHeld, consume

    config, ch, calls, envelope, _ = fixture_case(
        tmp_path, monkeypatch, phase="output_permanent"
    )
    config["artifact_delivery_attempts"] = 2
    with pytest.raises(DeliveryHeld):
        consume(config, once=True)
    assert ch.acks == [] and ch.nacks == [] and len(calls) == 1
    with sqlite3.connect(tmp_path / "state" / "role-state.sqlite") as c:
        assert c.execute(
            "SELECT attempts,state FROM role_artifact_deliveries"
        ).fetchone() == (2, "held")
        assert c.execute("SELECT status FROM tasks").fetchone()[0] == "completed"
    ch.connection.is_open = True
    ch.is_open = True
    ch.messages = [("command", 100, canonical(envelope))]
    with pytest.raises(DeliveryHeld):
        consume(config, once=True)
    assert ch.acks == [] and ch.nacks == [] and len(calls) == 1
    with sqlite3.connect(tmp_path / "state" / "role-state.sqlite") as c:
        assert c.execute(
            "SELECT attempts,state FROM role_artifact_deliveries"
        ).fetchone() == (2, "held")


@pytest.mark.parametrize(
    "kind,malformed",
    [
        ("command", "json"),
        ("cancel", "json"),
        ("command", "empty_task"),
        ("command", "outer_list"),
        ("command", "deep_json"),
        ("cancel", "huge_json_integer"),
        ("command", "bad_reference"),
        ("cancel", "bad_task_type"),
    ],
)
def test_poison_command_or_cancel_is_rejected_and_same_consumer_handles_next_valid(
    tmp_path, monkeypatch, kind, malformed
):
    from mideagent_models.broker import consume

    config, ch, calls, envelope, _ = fixture_case(tmp_path, monkeypatch)
    if malformed == "json":
        body = b"{"
    elif malformed == "deep_json":
        body = b"[" * 1500 + b"]" * 1500
    elif malformed == "huge_json_integer":
        body = b"9" * 5000
    elif malformed == "empty_task":
        body = canonical({**envelope, "task": {}})
    elif malformed == "outer_list":
        body = b"[]"
    elif malformed == "bad_reference":
        body = canonical(
            {
                **envelope,
                "source": {
                    "owner": envelope["source"]["owner"],
                    "reference": {"sha256": None},
                },
            }
        )
    else:
        body = canonical(
            {
                "version": 1,
                "role": "transcription",
                "task_id": [],
                "request_sha256": "a" * 64,
            }
        )
    ch.messages.insert(0, (kind, 1, body))
    consume(config)
    assert ch.nacks == [(1, False)] and ch.acks == [100]
    assert len(ch.results) == 1 and len(calls) == 1


@pytest.mark.parametrize(
    "phase,model_calls", [("input_integrity", 0), ("output_integrity", 1)]
)
def test_verified_integrity_failure_is_not_retried_as_transport(
    tmp_path, monkeypatch, phase, model_calls
):
    import sqlite3

    from mideagent_models.broker import consume

    config, ch, calls, _, _ = fixture_case(tmp_path, monkeypatch, phase=phase)
    consume(config, once=True)
    assert ch.acks == [] and ch.nacks == [(100, False)] and ch.results == []
    assert len(calls) == model_calls
    with sqlite3.connect(tmp_path / "state" / "role-state.sqlite") as c:
        assert c.execute(
            "SELECT attempts,state FROM role_artifact_deliveries"
        ).fetchone() == (1, "rejected")


def test_actual_pcm_clock_mismatch_only_rejects_its_delivery(tmp_path, monkeypatch):
    from mideagent_models.broker import consume

    config, ch, calls, envelope, _ = fixture_case(tmp_path, monkeypatch)
    bad = json.loads(canonical(envelope))
    bad["task"]["task_id"] = "3" * 32
    bad["task"]["timeline"] = [
        {"packed_start": 0, "packed_end": 2, "source_start": 10, "source_end": 12}
    ]
    ch.messages.insert(0, ("command", 1, canonical(bad)))
    consume(config)
    assert ch.nacks == [(1, False)] and ch.acks == [100] and len(calls) == 1
