"""R12/R13 only: cancellation fence versus receipt settlement, pending response action."""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie
from test_role_connection_recovery_boundaries import make_held, prepared
from video_service.cpu_agents import canonical, digest
from video_service.model_role_coordinator import ModelRoleCoordinator
from video_service.model_role_delivery import RoleResultDeliveries
from video_service.object_store import ObjectIntegrityError, ObjectStoreError
from video_service.rabbitmq_transport import Delivery

db, admin, movie = _db, _admin, _movie


def cut(runtime, action, predicate, code):
    pid = os.fork()
    if pid == 0:
        original = runtime.database.connection

        @contextmanager
        def connection():
            armed = False
            with original() as c:

                class Proxy:
                    def __getattr__(self, name):
                        return getattr(c, name)

                    def execute(self, sql, params=None, **kwargs):
                        nonlocal armed
                        if predicate(str(sql), params):
                            armed = True
                        return c.execute(sql, params, **kwargs)

                yield Proxy()
            if armed:
                os._exit(code)

        runtime.database.connection = connection
        try:
            action()
        except BaseException:
            os._exit(90)
        os._exit(91)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == code
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


def test_r12_reserved_next_attempt_then_product_cancel_does_not_hold_adopted_receipt(
    db, admin, movie, tmp_path
):
    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    receive = lambda: coordinator.receive(
        Delivery(canonical(ack), "mideagent.model.result.v1", ack["task_id"], None)
    )
    cut(
        runtime,
        receive,
        lambda sql, p: (
            "INSERT INTO node_runs" in sql
            and any(v == "translate" for v in p if isinstance(v, str))
        ),
        81,
    )
    with db.connection() as c:
        translation = c.execute(
            "SELECT * FROM node_runs WHERE node_type='translate'"
        ).fetchone()
        assert translation["status"] == "running"
        outbox = c.execute(
            "SELECT * FROM message_outbox WHERE id=%s", (translation["id"],)
        ).fetchone()
        assert outbox["published_at"] is None
    before = client.get(path).json()
    assert (
        client.post(path + "/cancel", json={"revision": before["revision"]}).status_code
        == 200
    )
    with db.connection() as c:
        reserved = c.execute(
            "SELECT request_sha256,status,request,generation FROM node_runs WHERE id=%s",
            (translation["id"],),
        ).fetchone()
        pending = c.execute(
            "SELECT * FROM message_outbox WHERE id=%s", (translation["id"],)
        ).fetchone()
        cancelled = c.execute(
            "SELECT cancel_requested,status,generation,revision FROM jobs"
        ).fetchone()
        receipt = c.execute(
            "SELECT attempts,revision FROM model_role_result_deliveries"
        ).fetchone()
    response = client.post(
        path + "/model-role/result-delivery",
        json={
            "task_id": ack["task_id"],
            "revision": receipt["revision"],
            "request_id": "explicit-reconcile-after-cancel",
        },
    )
    assert response.status_code == 200 and response.json()["state"] == "settled", (
        response.text
    )
    with db.connection() as c:
        assert (
            c.execute(
                "SELECT request_sha256,status,request,generation FROM node_runs WHERE id=%s",
                (translation["id"],),
            ).fetchone()
            == reserved
        )
        assert (
            c.execute(
                "SELECT * FROM message_outbox WHERE id=%s", (translation["id"],)
            ).fetchone()
            == pending
        )
        assert (
            c.execute(
                "SELECT cancel_requested,status,generation,revision FROM jobs"
            ).fetchone()
            == cancelled
        )
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == receipt["attempts"]
            == 1
        )
    assert cancelled["status"] == "cancelling" and len(calls) == 1


@pytest.mark.parametrize("boundary", ["settled", "exhausted", "rejected"])
def test_r13_pending_response_has_explicit_outcome_only_action(
    db, admin, movie, tmp_path, monkeypatch, boundary
):
    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    make_held(runtime, coordinator, ack, monkeypatch)
    original = runtime.store.read

    def fail(owner, ref, **kwargs):
        if ref == ack["result_ref"]:
            if boundary == "rejected":
                raise ObjectIntegrityError("controlled integrity error")
            raise ObjectStoreError("controlled final result GET error")
        return original(owner, ref, **kwargs)

    with monkeypatch.context() as m:
        if boundary != "settled":
            m.setattr(runtime.store, "read", fail)
        if boundary == "exhausted":
            task = client.get(path + "/model-role").json()["tasks"][0]
            response = client.post(
                path + "/model-role/result-delivery",
                json={
                    "task_id": ack["task_id"],
                    "revision": task["delivery_revision"],
                    "request_id": "known-failed-attempt",
                },
            )
            assert response.status_code == 200 and response.json()["state"] == "held"
        task = client.get(path + "/model-role").json()["tasks"][0]
        body = {
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "pending-response-original",
        }
        action = lambda: coordinator.recover_result(
            owner, job["id"], ack["task_id"], body["revision"], body["request_id"]
        )
        predicate = (
            (lambda sql, p: "SET state='settled'" in sql)
            if boundary == "settled"
            else (
                lambda sql, p: "SET state=%s,revision=revision+1,error_code=%s" in sql
            )
        )
        cut(runtime, action, predicate, 76 if boundary == "settled" else 82)
    task = client.get(path + "/model-role").json()["tasks"][0]
    assert task["pending_recovery"] == {
        "request_id": body["request_id"],
        "revision": body["revision"],
    }
    assert task["recovery_choices"] == ["settle_recovery_response"]
    with db.connection() as c:
        before = c.execute(
            "SELECT state,attempts,revision,error_code FROM model_role_result_deliveries"
        ).fetchone()

    def forbidden(*_args, **_kwargs):
        pytest.fail("response-only action must not fetch, attempt or dispatch")

    monkeypatch.setattr(RoleResultDeliveries, "attempt", forbidden)
    monkeypatch.setattr(RoleResultDeliveries, "reconcile_adoption", forbidden)
    monkeypatch.setattr(ModelRoleCoordinator, "_dispatch_after_result", forbidden)
    monkeypatch.setattr(runtime.store, "read", forbidden)
    with RoleResultDeliveries(coordinator).guard(ack["task_id"]):
        busy = client.get(path + "/model-role").json()["tasks"][0]
        assert busy["recovery_choices"] == []
        blocked = client.post(
            path + "/model-role/result-delivery",
            json={**body, "operation": "settle_recovery_response"},
        )
        assert blocked.status_code == 409
        with db.connection() as c:
            assert (
                c.execute(
                    "SELECT response FROM model_role_result_recoveries WHERE request_id=%s",
                    (body["request_id"],),
                ).fetchone()["response"]
                is None
            )
    response = client.post(
        path + "/model-role/result-delivery",
        json={**body, "operation": "settle_recovery_response"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == before["state"]
    with db.connection() as c:
        assert (
            c.execute(
                "SELECT state,attempts,revision,error_code FROM model_role_result_deliveries"
            ).fetchone()
            == before
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM model_role_result_recoveries WHERE response IS NULL"
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute("SELECT count(*) n FROM model_role_tool_calls").fetchone()["n"]
            == 1
        )
    assert (
        client.post(
            path + "/model-role/result-delivery",
            json={**body, "operation": "settle_recovery_response"},
        ).json()
        == response.json()
    )
    assert len(calls) == 1


def test_r13_unrecoverable_legacy_identity_is_explained_without_new_nonce(
    db, admin, movie, tmp_path, monkeypatch
):
    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    make_held(runtime, coordinator, ack, monkeypatch)
    task = client.get(path + "/model-role").json()["tasks"][0]
    payload = {
        "job_id": job["id"],
        "task_id": ack["task_id"],
        "revision": task["delivery_revision"],
        "request_id": "pre-029-original",
    }
    with db.connection() as c:
        c.execute(
            "INSERT INTO model_role_result_recoveries(owner_id,request_id,task_id,request_sha256)VALUES(%s,%s,%s,%s)",
            (owner, payload["request_id"], ack["task_id"], digest(payload)),
        )
    task = client.get(path + "/model-role").json()["tasks"][0]
    assert task["recovery_choices"] == []
    assert (
        task["recovery_block_reason"] == "legacy_pending_recovery_identity_unavailable"
    )
    assert task["pending_recovery"] == {
        "request_id": "pre-029-original",
        "revision": None,
    }
    denied = client.post(
        path + "/model-role/result-delivery",
        json={
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "replacement-not-authorized",
        },
    )
    assert denied.status_code == 409
    with db.connection() as c:
        assert (
            c.execute("SELECT count(*) n FROM model_role_result_recoveries").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == 1
        )
    assert len(calls) == 1


@pytest.mark.parametrize("cancel_during_dispatch", [True, False])
def test_r12_only_real_cancel_fence_is_a_nonfailure(
    db, admin, movie, tmp_path, monkeypatch, cancel_during_dispatch
):
    from video_service.postgres import Conflict
    from video_service.rabbitmq_controller import BrokerController

    runtime, owner, job, client, factory, coordinator, ack, calls, path = prepared(
        db, admin, movie, tmp_path
    )
    receive = lambda: coordinator.receive(
        Delivery(canonical(ack), "mideagent.model.result.v1", ack["task_id"], None)
    )
    cut(
        runtime,
        receive,
        lambda sql, p: (
            "INSERT INTO node_runs" in sql
            and any(v == "translate" for v in p if isinstance(v, str))
        ),
        81,
    )
    original = BrokerController.dispatch

    def dispatch(self, who, identity):
        if cancel_during_dispatch:
            current = runtime.get(owner, job["id"])
            runtime.cancel(owner, job["id"], current["revision"])
            return original(self, who, identity)
        raise Conflict("controlled_non_cancel_dispatch_conflict")

    monkeypatch.setattr(BrokerController, "dispatch", dispatch)
    task = client.get(path + "/model-role").json()["tasks"][0]
    response = client.post(
        path + "/model-role/result-delivery",
        json={
            "task_id": ack["task_id"],
            "revision": task["delivery_revision"],
            "request_id": "race-specific-settlement",
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == ("settled" if cancel_during_dispatch else "held")
    if not cancel_during_dispatch:
        assert response.json()["error_code"] == "result_dispatch_reconcile_held"
    with db.connection() as c:
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM message_outbox o JOIN node_runs n ON n.id=o.id WHERE n.node_type='translate'AND published_at IS NOT NULL"
            ).fetchone()["n"]
            == 0
        )
    assert len(calls) == 1


def test_r13_response_only_cannot_execute_an_admitted_but_unstarted_request(
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
        "request_id": "admitted-but-not-attempted",
    }
    cut(
        runtime,
        lambda: coordinator.recover_result(
            owner, job["id"], ack["task_id"], body["revision"], body["request_id"]
        ),
        lambda sql, p: "INSERT INTO model_role_result_recoveries" in sql,
        74,
    )
    task = client.get(path + "/model-role").json()["tasks"][0]
    assert task["recovery_choices"] == ["retry_result_delivery"]
    response = client.post(
        path + "/model-role/result-delivery",
        json={**body, "operation": "settle_recovery_response"},
    )
    assert response.status_code == 409
    with db.connection() as c:
        assert (
            c.execute("SELECT attempts FROM model_role_result_deliveries").fetchone()[
                "attempts"
            ]
            == 1
        )
        assert (
            c.execute("SELECT response FROM model_role_result_recoveries").fetchone()[
                "response"
            ]
            is None
        )
    assert len(calls) == 1
