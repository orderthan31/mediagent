"""R9/R10/R11: actual disposable PG, child exits and local controlled role."""

import base64
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from mideagent_models.broker import RoleReceiver
from mideagent_models.transcription import TranscriptionAgent
from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie
from test_model_role_user_connection import setup_api, start_user_role
from video_service.cpu_agents import canonical
from video_service.model_role_coordinator import ModelRoleCoordinator, RoleResultHeld
from video_service.model_role_delivery import RoleResultDeliveries
from video_service.model_role_tool import RoleToolBridge
from video_service.object_store import ObjectStoreError
from video_service.postgres.model_roles import ModelRoles
from video_service.rabbitmq_transport import Delivery

db, admin, movie = _db, _admin, _movie


def prepared(db, admin, movie, tmp_path):
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

    receiver = RoleReceiver(
        TranscriptionAgent(tmp_path / "role", Tool()), runtime.store, runtime.store
    )
    ack = receiver.deliver(commands[0])
    assert ack["status"] == "completed" and len(calls) == 1
    coordinator = ModelRoleCoordinator(runtime, factory)
    return runtime, owner, job, client, factory, coordinator, ack, calls, path


def make_held(runtime, coordinator, ack, monkeypatch):
    original = runtime.store.read

    def fail(owner, ref, **kwargs):
        if ref == ack["result_ref"]:
            raise ObjectStoreError("controlled temporary result GET failure")
        return original(owner, ref, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(runtime.store, "read", fail)
        with pytest.raises(RoleResultHeld):
            coordinator.receive(
                Delivery(
                    canonical(ack), "mideagent.model.result.v1", ack["task_id"], None
                )
            )


def crash_after_commit(runtime, operation, stage, code):
    pid = os.fork()
    if pid == 0:
        original = runtime.database.connection

        @contextmanager
        def connection():
            armed = False
            with original() as c:

                class Proxy:
                    def __getattr__(self, key):
                        return getattr(c, key)

                    def execute(self, query, params=None, **kwargs):
                        nonlocal armed
                        text = str(query)
                        if (
                            stage in {"receiving", "recovery_receiving"}
                            and "SET state='receiving'" in text
                        ):
                            armed = True
                        if (
                            stage == "admission"
                            and "INSERT INTO model_role_result_recoveries" in text
                        ):
                            armed = True
                        if (
                            stage == "accept_commit"
                            and "INSERT INTO message_inbox" in text
                        ):
                            armed = True
                        if (
                            stage == "adoption"
                            and "UPDATE model_role_tasks SET phase=" in text
                            and params
                            and params[0] == "accepted"
                        ):
                            armed = True
                        if stage == "response" and "SET state='settled'" in text:
                            armed = True
                        return c.execute(query, params, **kwargs)

                yield Proxy()
            if armed:
                os._exit(code)

        runtime.database.connection = connection
        try:
            operation()
        except BaseException:
            os._exit(90)
        os._exit(91)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == code, (
        "targeted durable boundary was not reached"
    )


@pytest.mark.parametrize(
    "stage,code",
    [
        ("receiving", 73),
        ("admission", 74),
        ("adoption", 75),
        ("response", 76),
        ("recovery_receiving", 77),
        ("accept_commit", 79),
    ],
)
def test_r9_explicit_recovery_survives_process_loss_without_model_recall(
    db, admin, movie, tmp_path, monkeypatch, stage, code
):
    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    body = None
    if stage in {"admission", "response", "recovery_receiving"}:
        make_held(runtime, coordinator, ack, monkeypatch)
        task = client.get(path + "/model-role").json()["tasks"][0]
        body = {
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "same-explicit-recovery",
        }
        operation = lambda: coordinator.recover_result(
            owner,
            job["id"],
            **{
                "task": ack["task_id"],
                "revision": body["revision"],
                "request_id": body["request_id"],
            },
        )
    else:
        operation = lambda: coordinator.receive(
            Delivery(canonical(ack), "mideagent.model.result.v1", ack["task_id"], None)
        )
    crash_after_commit(runtime, operation, stage, code)
    # Fork is used only to hit an actual os._exit boundary. A restarted controller
    # must not reuse the parent's inherited boto HTTP connection pool/socket state.
    import boto3
    from botocore.config import Config

    keys = json.loads(Path("/fixture/private/operator.json").read_text())
    runtime.store.client.close()
    runtime.store.client = boto3.client(
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
    with db.connection() as c:
        before = c.execute(
            "SELECT state,attempts,revision FROM model_role_result_deliveries"
        ).fetchone()
    # Redelivery is never an automatic orphan re-execution path.
    if before["state"] == "receiving":
        with pytest.raises(RoleResultHeld):
            coordinator.receive(
                Delivery(
                    canonical(ack), "mideagent.model.result.v1", ack["task_id"], None
                )
            )
    if body is not None and stage != "response":
        pending = client.get(path + "/model-role").json()["tasks"][0][
            "pending_recovery"
        ]
        assert pending == {
            "request_id": body["request_id"],
            "revision": body["revision"],
        }
    if body is None:
        task = client.get(path + "/model-role").json()["tasks"][0]
        assert "retry_result_delivery" in task["recovery_choices"]
        body = {
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "explicit-orphan-recovery",
        }
    refetch = []
    if stage in {"adoption", "response", "accept_commit"}:
        original = runtime.store.read

        def no_refetch(owner, ref, **kwargs):
            if ref == ack["result_ref"]:
                refetch.append(True)
            assert ref != ack["result_ref"], (
                "durable adoption must settle without fetching the completed result again"
            )
            return original(owner, ref, **kwargs)

        monkeypatch.setattr(runtime.store, "read", no_refetch)
    response = client.post(path + "/model-role/result-delivery", json=body)
    assert response.status_code == 200, response.text
    assert (
        response.json()["state"] == "settled"
        and response.json()["model_reexecuted"] is False
    ), response.text + str(refetch)
    assert (
        client.post(path + "/model-role/result-delivery", json=body).json()
        == response.json()
    )
    with db.connection() as c:
        after = c.execute(
            "SELECT state,attempts,revision FROM model_role_result_deliveries"
        ).fetchone()
        assert after["state"] == "settled" and after["attempts"] >= before["attempts"]
        assert after["attempts"] == (
            before["attempts"]
            if stage in {"adoption", "response", "accept_commit"}
            else before["attempts"] + 1
        )
        assert (
            c.execute("SELECT count(*) n FROM model_role_tool_calls").fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM node_runs WHERE node_type='translate'"
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM model_role_result_recoveries WHERE response IS NULL"
            ).fetchone()["n"]
            == 0
        )
    assert len(calls) == 1


@pytest.mark.parametrize("ack_first", [True, False])
def test_r10_cancel_terminal_is_stable_for_result_ack_order_and_duplicates(
    db, admin, movie, tmp_path, ack_first
):
    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    path = start_user_role(runtime, owner, job, client)
    current = client.get(path).json()
    cancel = client.post(path + "/cancel", json={"revision": current["revision"]})
    assert cancel.status_code == 200
    assert cancel.json()["cancellation"]["status"] == "newly_requested"
    repeated = client.post(path + "/cancel", json={"revision": current["revision"]})
    assert repeated.status_code == 200
    assert (
        repeated.json()["cancellation"]["status"] == "already_requested"
        and len(cancels) == 1
    )
    calls = []
    receiver = RoleReceiver(
        TranscriptionAgent(tmp_path / "role", lambda *_: calls.append(True) or []),
        runtime.store,
        runtime.store,
    )
    ack = receiver.deliver(cancels[0], kind="cancel_ack")
    result = receiver.deliver(commands[0])
    coordinator = ModelRoleCoordinator(runtime, factory)
    messages = [
        Delivery(canonical(ack), "mideagent.model.cancel_ack.v1", ack["task_id"], None),
        Delivery(
            canonical(result), "mideagent.model.result.v1", result["task_id"], None
        ),
    ]
    if not ack_first:
        messages.reverse()
    for delivery in [*messages, *messages]:
        coordinator.receive(delivery)
        with db.connection() as c:
            assert (
                c.execute("SELECT phase FROM model_role_tasks").fetchone()["phase"]
                == "cancelled"
            )
    assert calls == [] and registered == []
    assert client.get(path).json()["status"] == "cancelled"


def test_r11_completed_cancel_is_terminal_noop_not_applied(db, admin, movie, tmp_path):
    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    # Isolated terminal row only, not a claimed successful media execution.
    with db.connection() as c:
        c.execute(
            "UPDATE jobs SET status='completed'WHERE owner_id=%s AND id=%s",
            (owner, job["id"]),
        )
    before = runtime.get(owner, job["id"])
    response = client.post(
        "/api/renewal/jobs/" + job["id"] + "/cancel",
        json={"revision": before["revision"]},
    )
    assert response.status_code == 200
    cancel = response.json()["cancellation"]
    assert cancel["cancel_applied"] is False and cancel["status"] == "terminal_noop"
    assert cancel["role_delivery_complete"] is None
    after = runtime.get(owner, job["id"])
    assert tuple(
        after[k] for k in ["cancel_requested", "generation", "revision"]
    ) == tuple(before[k] for k in ["cancel_requested", "generation", "revision"])
    assert cancels == []


def test_role_operator_preserves_enabled_engine_binding(
    db, admin, movie, tmp_path, monkeypatch
):
    from app import operator
    from video_service.postgres.execution import Execution

    runtime, owner, job, client, factory, commands, cancels, registered = setup_api(
        db, admin, movie, tmp_path
    )
    factory.engine_factory = lambda: None
    dsn = tmp_path / "operator-dsn"
    dsn.write_text(db.dsn)
    bootstrap = tmp_path / "operator-bootstrap.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
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
    original = Execution.__init__
    flags = []

    def create(self, *args, **kwargs):
        flags.append(kwargs.get("engine_runtime_enabled"))
        original(self, *args, **kwargs)

    monkeypatch.setattr(Execution, "__init__", create)
    assert (
        operator.main(
            [
                "model-role-status",
                "--bootstrap-file",
                str(bootstrap),
                "--enable-broker",
                "--enable-registered-models",
                "--owner",
                owner,
                "--job",
                job["id"],
            ]
        )
        == 0
    )
    assert flags == [True]


def test_r9_live_guard_is_not_recovered_and_busy_api_creates_no_intent(
    db, admin, movie, tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    make_held(runtime, coordinator, ack, monkeypatch)
    task = client.get(path + "/model-role").json()["tasks"][0]
    body = {
        "task_id": ack["task_id"],
        "revision": task["delivery_revision"],
        "request_id": "explicit-after-owner-exits",
    }
    entered = threading.Event()
    release = threading.Event()

    def live():
        with RoleResultDeliveries(coordinator).guard(ack["task_id"]):
            entered.set()
            assert release.wait(8)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(live)
        assert entered.wait(5)
        try:
            active = client.get(path + "/model-role").json()["tasks"][0]
            assert (
                active["delivery_owner_active"] is True
                and active["recovery_choices"] == []
            )
            response = client.post(path + "/model-role/result-delivery", json=body)
            assert (
                response.status_code == 409
                and response.json()["code"] == "result_delivery_busy"
            )
            with db.connection() as c:
                assert (
                    c.execute(
                        "SELECT count(*) n FROM model_role_result_recoveries"
                    ).fetchone()["n"]
                    == 0
                )
                assert (
                    c.execute(
                        "SELECT attempts FROM model_role_result_deliveries"
                    ).fetchone()["attempts"]
                    == 1
                )
        finally:
            release.set()
        future.result(timeout=5)
    assert (
        client.post(path + "/model-role/result-delivery", json=body).json()["state"]
        == "settled"
    )
    assert len(calls) == 1


def test_r9_pending_request_crash_budget_is_never_reset(
    db, admin, movie, tmp_path, monkeypatch
):
    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    make_held(runtime, coordinator, ack, monkeypatch)
    task = client.get(path + "/model-role").json()["tasks"][0]
    body = {
        "task_id": ack["task_id"],
        "revision": task["delivery_revision"],
        "request_id": "same-budget-bound-recovery",
    }
    operation = lambda: coordinator.recover_result(
        owner, job["id"], ack["task_id"], body["revision"], body["request_id"]
    )
    for code in [77, 78]:
        crash_after_commit(runtime, operation, "receiving", code)
    with db.connection() as c:
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == 3
        )
    response = client.post(path + "/model-role/result-delivery", json=body)
    assert response.status_code == 200 and response.json()["state"] == "held"
    assert response.json()["error_code"] == "result_delivery_budget_exhausted"
    with db.connection() as c:
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == 3
        )
        assert (
            c.execute("SELECT count(*) n FROM model_role_tool_calls").fetchone()["n"]
            == 1
        )
    assert client.get(path + "/model-role").json()["tasks"][0]["recovery_choices"] == []
    assert len(calls) == 1
