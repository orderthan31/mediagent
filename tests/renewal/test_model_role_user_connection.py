"""User API/operator enrollment, actual disposable PG/TLS S3, local MQ/tool."""

import json
from contextlib import contextmanager
from pathlib import Path

import boto3
from app.renewal import create_app
from botocore.config import Config
from fastapi.testclient import TestClient
from test_execution import admin as _admin
from test_execution import admit
from test_execution import db as _db
from test_execution import movie as _movie
from test_foundation import login
from test_model_role_orchestration import formal
from video_service.cpu_agents import canonical
from video_service.object_store import S3ContentStore
from video_service.rabbitmq_transport import Delivery

db, admin, movie = _db, _admin, _movie


def setup_api(db, admin, movie, tmp_path):
    keys = json.loads(Path("/fixture/private/operator.json").read_text())
    client = boto3.client(
        "s3",
        endpoint_url="https://model-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=keys["object_user"],
        aws_secret_access_key=keys["object_password"],
        verify="/fixture/private/ca.pem",
        config=Config(
            signature_version="s3v4",
            retries={"total_max_attempts": 1},
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )
    (tmp_path / "appcache").mkdir()
    store = S3ContentStore(
        client, "model-role-boundary", tmp_path / "appcache", prefix="inputs"
    )
    runtime, owner, job = formal(db, admin, movie, tmp_path, store, prepare=False)
    commands = []
    cancels = []
    registered = []

    class RoleClient:
        def serve(self, role, handler, stop):
            assert role == "result"
            for delivery in list(factory.pending_results):
                handler(delivery)
                factory.result_acks.append(delivery.message_id)
                factory.pending_results.remove(delivery)

        def publish_command(self, packet):
            commands.append(packet)
            return True

        def publish_cancel(self, packet):
            cancels.append(packet)
            return True

    class Registered:
        def publish(self, packet):
            registered.append(packet)
            return True

    @contextmanager
    def role_factory():
        yield RoleClient()

    @contextmanager
    def registered_factory():
        yield Registered()

    @contextmanager
    def factory():
        raise AssertionError("no CPU publication in this narrow fixture")
        yield

    factory.pending_results = []
    factory.result_acks = []
    factory.vocalization_runtime = None
    factory.registered_factory = registered_factory
    factory.model_role_factory = role_factory
    factory.model_role_result_store = store
    factory.registered_policy_sha256 = "a" * 64
    for role in ["transcription", "translation"]:
        runner = getattr(runtime, role + "_runtime")
        runner.policy_sha256 = "a" * 64
        setattr(factory, role + "_runtime", runner)
    app = create_app(
        db,
        allowed_origins=["http://testserver"],
        secure_cookies=False,
        content_store=store,
        local_execution=True,
        credential_store=runtime.transcription_runtime.credentials,
        transcription_runtime=runtime.transcription_runtime,
        translation_runtime=runtime.translation_runtime,
        broker_factory=factory,
    )
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login(client, admin)
    return runtime, owner, job, client, factory, commands, cancels, registered


def test_explicit_api_enrollment_routes_new_role_and_operator_result_to_next_dispatch(
    db, admin, movie, tmp_path, monkeypatch
):
    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = "/api/renewal/jobs/" + job["id"]
    body = {"revision": job["revision"], "request_id": "fresh-role-enrollment"}
    reply = client.post(path + "/model-role/enrollment", json=body)
    assert reply.status_code == 200, reply.text
    assert reply.json()["enrolled"] is True
    assert (
        client.post(path + "/model-role/enrollment", json=body).json() == reply.json()
    )
    assert commands == []
    admit(runtime, owner, job["id"])
    for _ in range(2):
        command = runtime.claim_next(owner, job["id"])
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed"
        runtime.accept(owner, command, result)
    response = client.post(path + "/run", json={})
    assert response.status_code == 200, response.text
    assert len(commands) == 1 and not registered
    import base64

    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.model_role_coordinator import ModelRoleCoordinator
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()
    bridge = RoleToolBridge(ModelRoles(runtime), chunk_concurrency=2)

    class Tool:
        def for_chunk(self, task, chunk):
            return lambda model, audio, language: bridge.invoke(
                {
                    "task_id": task["task_id"],
                    "chunk_index": chunk["index"],
                    "model": model,
                    "source_language": language,
                    "audio_base64": base64.b64encode(audio).decode(),
                }
            )

    worker = RoleReceiver(
        TranscriptionAgent(tmp_path / "role", Tool()), runtime.store, runtime.store
    )
    ack = worker.deliver(commands[0])
    assert ack["status"] == "completed"
    delivery = Delivery(
        canonical(ack), "mideagent.model.result.v1", ack["task_id"], None
    )
    coordinator = ModelRoleCoordinator(runtime, factory)
    from app import operator

    dsnfile = tmp_path / "operator-dsn"
    dsnfile.write_text(db.dsn)
    bootstrap = tmp_path / "operator-bootstrap.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsnfile),
                "content_root": str(tmp_path),
                "allowed_origins": ["http://testserver"],
                "host": "127.0.0.1",
                "port": 9418,
                "secure_cookies": False,
            }
        )
    )
    monkeypatch.setattr(
        operator,
        "runtime_components",
        lambda *args, **kwargs: (
            runtime.store,
            runtime.transcription_runtime.credentials,
            factory,
        ),
    )
    # The local transport factory is affinity-bound to this exact real fixture DB.
    monkeypatch.setattr(
        "video_service.postgres.Database",
        lambda dsn: (
            db
            if dsn == db.dsn
            else (_ for _ in ()).throw(AssertionError("wrong fixture DSN"))
        ),
    )
    factory.pending_results = [delivery]
    assert (
        operator.main(
            [
                "consume-model-role-results",
                "--bootstrap-file",
                str(bootstrap),
                "--enable-broker",
                "--enable-registered-models",
                "--allow-controlled-models",
            ]
        )
        == 0
    )
    assert factory.result_acks == [delivery.message_id]

    assert calls == [True] and len(registered) == 1
    state = client.get(path).json()
    asr = next(r for r in state["runs"] if r["node_type"] == "transcribe")
    translation = next(r for r in state["runs"] if r["node_type"] == "translate")
    assert (
        asr["status"] == "completed"
        and translation["inputs"]["transcript"]
        == asr["result"]["outputs"]["transcript"]
    )
    assert coordinator.receive(delivery) is None
    assert calls == [True] and len(registered) == 1
    public = client.get(path + "/model-role").json()
    assert public["tasks"][0]["state"] == "accepted"


def start_user_role(runtime, owner, job, client):
    path = "/api/renewal/jobs/" + job["id"]
    response = client.post(
        path + "/model-role/enrollment",
        json={"revision": job["revision"], "request_id": "new-explicit"},
    )
    assert response.status_code == 200, response.text
    admit(runtime, owner, job["id"])
    for _ in range(2):
        command = runtime.claim_next(owner, job["id"])
        result = runtime.execute_command(owner, command)
        runtime.accept(owner, command, result)
    assert client.post(path + "/run", json={}).status_code == 200
    return path


def test_product_cancel_creates_scoped_role_control_and_ack_settles_same_attempt(
    db, admin, movie, tmp_path
):
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.model_role_coordinator import ModelRoleCoordinator

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = start_user_role(runtime, owner, job, client)
    current = client.get(path).json()
    response = client.post(path + "/cancel", json={"revision": current["revision"]})
    assert response.status_code == 200, response.text
    assert response.json()["cancel_requested"] is True
    assert response.json()["cancellation"]["role_delivery_complete"] is False
    assert len(cancels) == 1 and cancels[0]["task_id"] == commands[0]["task"]["task_id"]
    assert (
        client.post(
            path + "/cancel", json={"revision": current["revision"]}
        ).status_code
        == 200
    )
    assert len(cancels) == 1
    calls = []
    receiver = RoleReceiver(
        TranscriptionAgent(
            tmp_path / "cancel-role", lambda *_: calls.append(True) or []
        ),
        runtime.store,
        runtime.store,
    )
    ack = receiver.deliver(cancels[0], kind="cancel_ack")
    coordinator = ModelRoleCoordinator(runtime, factory)
    coordinator.receive(
        Delivery(canonical(ack), "mideagent.model.cancel_ack.v1", ack["task_id"], None)
    )
    assert receiver.deliver(commands[0])["status"] == "cancelled" and calls == []
    final = client.get(path).json()
    assert final["status"] == "cancelled"
    public = client.get(path + "/model-role").json()
    assert public["tasks"][0]["cancel_delivery"] == "acknowledged"
    assert not registered


def test_cancel_lock_timeout_is_retryable_not_applied_then_explicit_retry_succeeds(
    db, admin, movie, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from video_service.postgres.model_call_fence import model_call_fence

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = start_user_role(runtime, owner, job, client)
    before = runtime.get(owner, job["id"])
    entered = threading.Event()
    release = threading.Event()
    original = db.connection

    def inflight():
        with model_call_fence(db, owner, job["id"]):
            entered.set()
            assert release.wait(5)

    @contextmanager
    def connection():
        with original() as c:
            c.execute("SET LOCAL lock_timeout='100ms'")
            yield c

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(inflight)
        assert entered.wait(5)
        monkeypatch.setattr(db, "connection", connection)
        try:
            response = client.post(
                path + "/cancel", json={"revision": before["revision"]}
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "cancel_admission_busy"
            assert (
                response.json()["retryable"] is True
                and response.json()["cancel_applied"] is False
            )
            latest = client.get(path)
            assert latest.status_code == 200, latest.text
            with original() as read:
                after = read.execute(
                    "SELECT cancel_requested,generation,revision FROM jobs WHERE owner_id=%s AND id=%s",
                    (owner, job["id"]),
                ).fetchone()
            assert tuple(
                after[k] for k in ["cancel_requested", "generation", "revision"]
            ) == tuple(
                before[k] for k in ["cancel_requested", "generation", "revision"]
            )
            assert cancels == []
        finally:
            release.set()
        future.result(timeout=5)
    assert (
        client.post(path + "/cancel", json={"revision": before["revision"]}).status_code
        == 200
    )
    assert len(cancels) == 1


def test_official_operator_has_exact_job_role_modes_and_private_transport_binding(
    capsys, monkeypatch
):
    from app import operator, server

    monkeypatch.setattr("sys.argv", ["operator"])
    import pytest

    with pytest.raises(SystemExit) as exited:
        operator.main(["--help"])
    assert exited.value.code == 0
    helptext = capsys.readouterr().out
    for name in [
        "consume-model-role-results",
        "enroll-model-role",
        "model-role-status",
        "--owner",
        "--job",
        "--revision",
        "--request-id",
    ]:
        assert name in helptext
    assert {
        "model_role_broker_config_file",
        "model_role_result_config_file",
    } <= server.OPTIONAL_FIELDS
    from video_service.model_role_broker import ModelRoleBrokerConfig

    cfg = ModelRoleBrokerConfig(namespace="fresh_roles", url_env="FRESH_ROLE_URL")
    assert cfg.commands == "fresh_roles.transcription.commands.v1"
    assert cfg.queue("result") == "fresh_roles.transcription.result_inbox.v1"


def test_held_result_transport_recovery_reuses_exact_completed_result_without_model_call(
    db, admin, movie, tmp_path, monkeypatch
):
    import base64

    import pytest
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.model_role_coordinator import (
        ModelRoleCoordinator,
        RoleResultHeld,
    )
    from video_service.model_role_tool import RoleToolBridge
    from video_service.object_store import ObjectStoreError
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = start_user_role(runtime, owner, job, client)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            return []

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()
    bridge = RoleToolBridge(ModelRoles(runtime), chunk_concurrency=2)

    class Tool:
        def for_chunk(self, task, chunk):
            return lambda model, audio, language: bridge.invoke(
                {
                    "task_id": task["task_id"],
                    "chunk_index": chunk["index"],
                    "model": model,
                    "source_language": language,
                    "audio_base64": base64.b64encode(audio).decode(),
                }
            )

    ack = RoleReceiver(
        TranscriptionAgent(tmp_path / "held-role", Tool()), runtime.store, runtime.store
    ).deliver(commands[0])
    assert ack["status"] == "completed"
    coordinator = ModelRoleCoordinator(runtime, factory)
    original = runtime.store.read
    fail = True

    def read(owner, ref, **kwargs):
        if fail and ref == ack["result_ref"]:
            raise ObjectStoreError("controlled result GET unavailable")
        return original(owner, ref, **kwargs)

    monkeypatch.setattr(runtime.store, "read", read)
    with pytest.raises(RoleResultHeld):
        coordinator.receive(
            Delivery(canonical(ack), "mideagent.model.result.v1", ack["task_id"], None)
        )
    public = client.get(path + "/model-role")
    assert public.status_code == 200
    task = public.json()["tasks"][0]
    assert task["state"] == "held" and task["reason"] == "result_transport_unavailable"
    assert task["reserved_calls"] == 1 and task["max_calls"] == 3
    assert task["recovery_choices"] == ["retry_result_delivery"] and not registered
    fail = False
    body = {
        "task_id": ack["task_id"],
        "revision": task["delivery_revision"],
        "request_id": "explicit-artifact-recovery",
    }
    recovered = client.post(path + "/model-role/result-delivery", json=body)
    assert recovered.status_code == 200, recovered.text
    assert (
        recovered.json()["state"] == "settled"
        and recovered.json()["model_reexecuted"] is False
    )
    assert (
        client.post(path + "/model-role/result-delivery", json=body).json()
        == recovered.json()
    )
    assert calls == [True] and len(commands) == 1 and len(registered) == 1
    with db.connection() as c:
        row = c.execute(
            "SELECT attempts,state FROM model_role_result_deliveries"
        ).fetchone()
        assert row == {"attempts": 2, "state": "settled"}


def test_unknown_model_outcome_has_no_result_delivery_recovery_or_recall(
    db, admin, movie, tmp_path
):
    import base64

    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.model_role_coordinator import ModelRoleCoordinator
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = start_user_role(runtime, owner, job, client)
    calls = []

    class Adapter:
        def transcribe(self, *_):
            calls.append(True)
            raise TimeoutError("controlled unknown reply")

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda *_: Adapter()
    bridge = RoleToolBridge(ModelRoles(runtime), chunk_concurrency=2)

    class Tool:
        def for_chunk(self, task, chunk):
            return lambda model, audio, language: bridge.invoke(
                {
                    "task_id": task["task_id"],
                    "chunk_index": chunk["index"],
                    "model": model,
                    "source_language": language,
                    "audio_base64": base64.b64encode(audio).decode(),
                }
            )

    worker = RoleReceiver(
        TranscriptionAgent(tmp_path / "unknown-role", Tool()),
        runtime.store,
        runtime.store,
    )
    ack = worker.deliver(commands[0])
    assert ack["status"] == "held"
    coordinator = ModelRoleCoordinator(runtime, factory)
    coordinator.receive(
        Delivery(canonical(ack), "mideagent.model.result.v1", ack["task_id"], None)
    )
    task = client.get(path + "/model-role").json()["tasks"][0]
    assert task["state"] == "held" and task["reason"] == "model_reply_unknown"
    assert task["reserved_calls"] == task["reported_model_calls"] == 1
    assert task["call_issues"] == [
        {"chunk_index": 0, "status": "unknown", "error_code": "TimeoutError"}
    ]
    assert task["recovery_choices"] == []
    denied = client.post(
        path + "/model-role/result-delivery",
        json={
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "no-model-rerun",
        },
    )
    assert denied.status_code == 409
    assert worker.deliver(commands[0]) == ack
    assert len(calls) == 1 and not registered


def test_enrollment_rejects_missing_csrf_and_started_or_foreign_jobs(
    db, admin, movie, tmp_path
):
    from fastapi.testclient import TestClient
    from video_service.postgres.accounts import Accounts

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = "/api/renewal/jobs/" + job["id"]
    body = {"revision": job["revision"], "request_id": "no-implicit-old-work"}
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post(path + "/model-role/enrollment", json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    import secrets

    password = secrets.token_urlsafe(24)
    outsider = Accounts(db).create("role-reader", password, actor_id=owner)
    # Shared status is readable, but enrollment/recovery/cancel remain owner-bound.
    reader = TestClient(client.app)
    reader.headers["Origin"] = "http://testserver"
    login(reader, (outsider, password))
    assert reader.get(path + "/model-role").status_code == 200
    assert reader.post(path + "/model-role/enrollment", json=body).status_code == 404
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    assert command["agent"]["id"] == "extract_audio"
    assert client.post(path + "/model-role/enrollment", json=body).status_code == 409
    with db.connection() as c:
        assert (
            c.execute("SELECT count(*) n FROM model_role_enrollments").fetchone()["n"]
            == 0
        )
        assert c.execute("SELECT count(*) n FROM model_role_tasks").fetchone()["n"] == 0
    assert commands == cancels == registered == []
