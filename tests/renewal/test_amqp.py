"""Real Pika SDK + deterministic channel seam; NOT a live RabbitMQ test.

CPU/S3/PG tests below execute actual synthetic media and durable persistence.
No operational endpoint or queue is discovered, opened or consumed.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pika
import pytest
from mideagent_cpu.broker import CpuHandler
from test_execution import admit, graph, setup
from test_execution import movie as _movie_fixture
from test_foundation import admin as _admin_fixture
from test_foundation import db as _db_fixture
from test_foundation import login
from test_object_agents import command
from test_object_agents import objects as _objects_fixture
from video_service.agent_protocol import CPU_AGENTS
from video_service.object_agent import ObjectAgentExecutor
from video_service.postgres import Conflict
from video_service.postgres.execution import Execution
from video_service.rabbitmq_controller import BrokerController
from video_service.rabbitmq_transport import (
    RESULT,
    BrokerConfig,
    BrokerError,
    InvalidMessage,
    RabbitClient,
    decode,
    envelope,
)

admin, db, movie, objects = (
    _admin_fixture,
    _db_fixture,
    _movie_fixture,
    _objects_fixture,
)


def synthetic_command():
    return command(
        {
            "storage_key": "blobs/" + "a" * 64,
            "sha256": "a" * 64,
            "bytes": 1,
            "type": "video",
        },
        "analyze",
    )


class ChannelSeam:
    """Explicit test double, using real Pika BasicProperties/error classes."""

    def __init__(self, stop=None):
        self.events = []
        self.is_open = True
        self.stop = stop
        self.callback = None
        self.cancelled = False
        self.publish_failure = None
        self.acks = []
        self.nacks = []
        self.published = []

    def event(self, op, **fields):
        self.events.append((op, threading.get_ident(), fields))

    def confirm_delivery(self):
        self.event("confirm")

    def exchange_declare(self, **kw):
        self.event("exchange", **kw)

    def queue_declare(self, **kw):
        self.event("queue", **kw)

    def queue_bind(self, **kw):
        self.event("bind", **kw)

    def basic_publish(self, **kw):
        self.event("publish", **kw)
        if self.publish_failure:
            raise self.publish_failure
        self.published.append(kw)
        # This is the documented Pika BlockingChannel contract.

    def basic_qos(self, **kw):
        self.event("qos", **kw)

    def basic_consume(self, **kw):
        self.event("consume", auto_ack=kw["auto_ack"])
        self.callback = kw["on_message_callback"]
        return "synthetic-consumer"

    def basic_cancel(self, tag):
        self.event("cancel", tag=tag)
        self.cancelled = True
        return []

    def basic_ack(self, **kw):
        self.event("ack", **kw)
        self.acks.append(kw)
        if self.stop:
            self.stop.set()

    def basic_nack(self, **kw):
        self.event("nack", **kw)
        self.nacks.append(kw)
        if self.stop:
            self.stop.set()


class ConnectionSeam:
    def __init__(self, channel, delivery=None, on_tick=None):
        self.c = channel
        self.is_open = True
        self.delivery = delivery
        self.ticks = 0
        self.on_tick = on_tick

    def channel(self):
        return self.c

    def process_data_events(self, time_limit):
        self.ticks += 1
        if self.delivery and self.c.callback and not self.c.cancelled:
            d, self.delivery = self.delivery, None
            props = pika.BasicProperties(
                type=d.message_type,
                message_id=d.message_id,
                correlation_id=d.correlation_id,
                content_type=d.content_type,
                content_encoding=d.content_encoding,
            )
            self.c.callback(self.c, SimpleNamespace(delivery_tag=1), props, d.body)
        if self.on_tick:
            self.on_tick(self.ticks)
        time.sleep(min(time_limit, 0.002))

    def close(self):
        self.is_open = False
        self.c.is_open = False


def client_seam(delivery=None, stop=None, on_tick=None):
    channel = ChannelSeam(stop)
    connection = ConnectionSeam(channel, delivery, on_tick)
    config = BrokerConfig("isolated." + uuid4().hex, "SYNTHETIC_BROKER_URL", True)
    return RabbitClient(config, connection, pika), channel, connection


def test_real_sdk_parameters_require_explicit_tls_or_loopback_and_redact():
    cfg = BrokerConfig("isolated.test", "TEST_AMQP_URL")
    env = {"TEST_AMQP_URL": "amqps://synthetic:sentinel@broker.invalid/isolated"}
    params = cfg.parameters(environ=env, sdk=pika)
    assert isinstance(params, pika.URLParameters)
    assert params.heartbeat == 30 and params.connection_attempts == 1
    assert params.ssl_options.context.check_hostname
    assert "sentinel" not in repr(cfg)
    for endpoint in [
        "amqp://synthetic:sentinel@broker.invalid/isolated",
        "amqp://synthetic:sentinel@127.0.0.1/isolated",
        "amqps://synthetic:sentinel@broker.invalid/",
        "amqps://synthetic:sentinel@broker.invalid/isolated?heartbeat=0",
    ]:
        with pytest.raises(BrokerError, match="invalid_broker_endpoint") as error:
            cfg.parameters(environ={"TEST_AMQP_URL": endpoint}, sdk=pika)
        assert "sentinel" not in str(error.value)
    local = replace(cfg, allow_loopback=True)
    assert (
        local.parameters(
            environ={"TEST_AMQP_URL": "amqp://synthetic:sentinel@127.0.0.1/isolated"},
            sdk=pika,
        ).ssl_options
        is None
    )
    with pytest.raises(BrokerError):
        BrokerConfig.from_env(
            "SETTINGS",
            environ={
                "SETTINGS": json.dumps(
                    {
                        "namespace": "isolated.test",
                        "url_env": "TEST_AMQP_URL",
                        "password": "sentinel",
                    }
                )
            },
        )


def test_envelope_identity_role_shape_and_bounded_payload():
    owner, cmd = uuid4().hex, synthetic_command()
    delivery = envelope(owner, cmd)
    assert decode(delivery, role="analyze")["command"] == cmd
    for bad in [
        replace(delivery, message_id=uuid4().hex),
        replace(delivery, correlation_id=uuid4().hex),
        replace(delivery, content_type="text/plain"),
        replace(delivery, body=b"x" * 131073),
    ]:
        with pytest.raises(InvalidMessage):
            decode(bad)
    with pytest.raises(InvalidMessage):
        decode(delivery, role="encode")
    with pytest.raises(InvalidMessage):
        envelope(owner, {**cmd, "credentials": {"secret": "sentinel"}})
    with pytest.raises(InvalidMessage):
        decode(
            replace(
                delivery,
                message_type=RESULT,
                body=json.dumps(
                    {"version": 1, "owner": owner, "command": cmd, "result": None}
                ).encode(),
            ),
            result=True,
        )


def test_actual_sdk_handshake_failure_is_sanitized(monkeypatch):
    # Negative wire probe only: this socket is not an AMQP broker/emulator.
    monkeypatch.setattr(logging.getLogger("pika"), "disabled", True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]

        def close_handshake():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                return connection.recv(8)

        cfg = BrokerConfig("isolated.handshake", "TEST_AMQP_URL", True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            wire = pool.submit(close_handshake)
            with pytest.raises(BrokerError, match="broker_connection_failed") as error:
                RabbitClient.connect(
                    cfg,
                    environ={
                        "TEST_AMQP_URL": f"amqp://synthetic:sentinel@127.0.0.1:{port}/isolated"
                    },
                )
            assert wire.result(timeout=5).startswith(b"AMQP")
        assert "sentinel" not in str(error.value)


def test_topology_is_explicit_and_roles_have_separate_durable_queues():
    client, channel, _ = client_seam()
    assert [op for op, *_ in channel.events] == ["confirm"]
    client.declare()
    queues = [fields for op, _, fields in channel.events if op == "queue"]
    assert len(queues) == 2 * (len(CPU_AGENTS) + 1) and all(
        q["durable"] for q in queues
    )
    assert len({q["queue"] for q in queues}) == len(queues)
    result = next(q for q in queues if q["queue"] == client.config.queue("result"))
    assert "x-message-ttl" not in result["arguments"]
    analyze = next(q for q in queues if q["queue"] == client.config.queue("analyze"))
    assert analyze["arguments"]["x-message-ttl"] == 60000
    assert analyze["arguments"]["x-dead-letter-exchange"] == client.config.dead


def test_confirmed_publish_uses_real_sdk_properties_and_rejects_nack():
    client, channel, _ = client_seam()
    delivery = envelope(uuid4().hex, synthetic_command())
    assert client.publish(delivery) is True
    sent = channel.published[0]
    props = sent["properties"]
    assert isinstance(props, pika.BasicProperties)
    assert props.delivery_mode == 2 and sent["mandatory"] is True
    assert props.message_id == delivery.message_id and props.expiration == "60000"
    # Exercise the SDK's actual property encoder, not an invented AMQP object.
    assert b"application/json" in b"".join(props.encode())
    for failure in [pika.exceptions.NackError([]), pika.exceptions.UnroutableError([])]:
        channel.publish_failure = failure
        with pytest.raises(BrokerError, match="broker_publish_unconfirmed"):
            client.publish(delivery)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(BrokerError, match="broker_thread_mismatch"),
    ):
        pool.submit(client.publish, delivery).result()


def test_consumer_services_heartbeat_and_drains_before_ack_on_owner_thread():
    stop, started = threading.Event(), threading.Event()
    delivery = envelope(uuid4().hex, synthetic_command())

    def on_tick(count):
        if started.is_set() and count >= 3:
            stop.set()

    client, channel, connection = client_seam(delivery, on_tick=on_tick)
    owner_thread = threading.get_ident()

    def handle(item):
        assert threading.get_ident() != owner_thread
        assert decode(item)["command"]["agent"]["id"] == "analyze"
        started.set()
        deadline = time.monotonic() + 2
        while not stop.is_set() and time.monotonic() < deadline:
            time.sleep(0.002)
        assert stop.is_set()
        time.sleep(0.01)

    client.serve("analyze", handle, stop)
    ops = [op for op, *_ in channel.events]
    assert ops.index("cancel") < ops.index("ack")
    assert connection.ticks >= 3 and len(channel.acks) == 1
    assert all(tid == owner_thread for _, tid, _ in channel.events)
    assert (
        next(fields for op, _, fields in channel.events if op == "qos")[
            "prefetch_count"
        ]
        == 1
    )


def test_poison_is_dead_lettered_and_failed_confirmation_is_not_acked():
    delivery = envelope(uuid4().hex, synthetic_command())
    stop = threading.Event()
    client, channel, _ = client_seam(delivery, stop)

    def poison(_):
        raise InvalidMessage("poison")

    client.serve("analyze", poison, stop)
    assert channel.nacks == [{"delivery_tag": 1, "requeue": False}]
    assert channel.acks == []
    client, channel, _ = client_seam(delivery)
    channel.publish_failure = pika.exceptions.NackError([])
    with pytest.raises(BrokerError, match="broker_consumer_stopped"):
        client.serve("analyze", lambda _: delivery, threading.Event())
    assert channel.acks == []


def test_imports_and_cli_do_not_connect_without_opt_in():
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": ":".join(
            str(root / p) for p in ("packages/shared", "agents/cpu", "apps/api")
        ),
    }
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            """import socket,sys
def blocked(*args, **kw): raise AssertionError('unexpected connection')
socket.socket.connect=blocked
import video_service.rabbitmq_transport
import mideagent_cpu.broker
assert 'pika' not in sys.modules
assert 'psycopg' not in sys.modules
print('import-no-connect-ok')
""",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert check.returncode == 0, check.stderr
    for module, args in [
        (
            "mideagent_cpu.broker",
            [
                "--agent",
                "analyze",
                "--broker-config-env",
                "UNSET",
                "--object-config-env",
                "UNSET",
            ],
        ),
        ("app.broker_server", ["declare-topology", "--broker-config-env", "UNSET"]),
    ]:
        result = subprocess.run(
            [sys.executable, "-m", module, *args],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2 and "--enable-broker" in result.stderr


class PublisherSeam:
    def __init__(self):
        self.messages = []
        self.fail = False

    def publish(self, delivery):
        if self.fail:
            raise BrokerError("injected_unconfirmed")
        self.messages.append(delivery)
        return True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_api_dispatch_cpu_object_receipt_and_durable_result_controller(
    objects, db, admin, movie
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    store, _, _, env = objects
    publisher = PublisherSeam()
    factory = lambda: publisher
    runtime = Execution(db, store)
    controller = BrokerController(runtime, factory)
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, graph("encode", "validate_video"))
    admit(runtime, owner, job["id"])
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=store,
        local_execution=True,
        broker_factory=factory,
    )
    client = TestClient(app)
    login(client, admin)
    assert publisher.messages == [], "Startup must not publish or consume"
    publisher.fail = True
    path = "/api/renewal/jobs/" + job["id"] + "/run"
    assert client.post(path, json={}).status_code == 503
    publisher.fail = False
    response = client.post(path, json={})
    assert response.status_code == 200 and response.json()["status"] == "running"
    assert client.post(path, json={}).status_code == 200
    assert len(publisher.messages) == 1
    executor = ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=env)
    assert all(
        "BROKER" not in key and key != "MIDEAGENT_TEST_DSN" for key in executor.env
    )
    first = CpuHandler("encode", executor)(publisher.messages[0])
    assert CpuHandler("encode", executor)(publisher.messages[0]) == first
    result_data = decode(first, result=True)
    assert store.path(owner, result_data["result"]["outputs"]["video"]).is_file()
    # Controller does real PG/S3 work off-thread; channel seam checks ACK only after
    # durable acceptance and follow-up publication have returned.
    stop = threading.Event()
    result_client, channel, _ = client_seam(first, stop)
    result_client.serve("result", controller.receive, stop)
    assert len(channel.acks) == 1 and len(publisher.messages) == 2
    with db.connection() as conn:
        saved = conn.execute(
            "SELECT status FROM node_runs WHERE id=%s", (first.message_id,)
        ).fetchone()
    assert saved["status"] == "completed"
    controller.receive(first)
    assert len(publisher.messages) == 2, "Duplicate result must not dispatch twice"
    second = CpuHandler("validate_video", executor)(publisher.messages[1])
    controller.receive(second)
    assert runtime.get(owner, job["id"])["status"] == "completed"
    assert decode(second, result=True)["command"]["agent"]["id"] == "validate_video"
    # A changed result identity/owner never reaches durable acceptance.
    with pytest.raises(InvalidMessage):
        controller.receive(replace(first, correlation_id=uuid4().hex))


def test_expired_unpublished_attempt_cannot_be_sent(objects, db, admin, movie):
    store, _, _, _ = objects
    runtime = Execution(db, store)
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, graph("analyze"))
    admit(runtime, owner, job["id"])
    cmd = runtime.claim_next(owner, job["id"])
    with db.connection() as conn:
        conn.execute(
            "UPDATE node_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (cmd["attempt_id"],),
        )
    pub = PublisherSeam()
    with pytest.raises(Conflict):
        BrokerController(runtime, lambda: pub).publish_exact(
            owner, job["id"], cmd["attempt_id"]
        )
    assert pub.messages == []


def test_unknown_remote_attempt_is_quarantined_without_launch(objects, movie):
    store, _, _, env = objects
    owner = uuid4().hex
    ref = store.put(owner, [movie], "video")
    cmd = command(ref)
    assert store.claim_attempt(owner, cmd) is None
    executor = ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=env)
    with pytest.raises(InvalidMessage, match="attempt_unknown"):
        CpuHandler("encode", executor)(envelope(owner, cmd))
    assert not (store.owner_root(owner) / "attempts").exists()
