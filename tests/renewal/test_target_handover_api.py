"""Normal product authentication; no Docker/source pin input in API payloads."""

import os
import secrets
from uuid import uuid4

from app.renewal import create_app
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.target_handover import TargetHandover


def test_handover_is_opt_in_admin_csrf_and_candidate_only(tmp_path):
    assert os.environ.get("MIDEAGENT_CONTROL_DISPOSABLE") == "1"
    base = Database(os.environ["MIDEAGENT_JOURNAL_TEST_DSN"])
    schema = "handover_http_" + uuid4().hex
    with base.connection() as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(make_conninfo(base.dsn, options="-c search_path=" + schema))
    db.migrate()
    store = RemoteControl(db)
    ledger = TargetHandover(store)
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        remote_control=store,
        target_handover=ledger,
    )
    path = "/api/admin/agents/encode/target-handover"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        password = secrets.token_urlsafe(28)
        assert (
            client.post(
                "/api/auth/bootstrap",
                json={"username": "handover-admin", "password": password},
            ).status_code
            == 201
        )
        login = client.post(
            "/api/auth/login", json={"username": "handover-admin", "password": password}
        )
        assert login.status_code == 200
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        body = {"candidate_id": uuid4().hex}
        assert client.post(path + "/preview", json=body).status_code == 403
        assert (
            client.post(
                path + "/preview",
                json={**body, "container_id": "a" * 64},
                headers=headers,
            ).status_code
            == 422
        )
        from test_target_handover import setup_case
        from video_service.target_handover import HandoverHost

        admin = login.json()["user"]["id"]
        state = setup_case((db, admin), tmp_path)
        _, _, _, group, wid, old, new, receipts, calls, *_ = state
        executor = HandoverHost(ledger, old, new, {group: [wid]}, receipts)
        candidate = executor.prepare(group)
        actual_path = "/api/admin/agents/" + group + "/target-handover"
        assert client.get(actual_path).status_code == 200
        preview = client.post(
            actual_path + "/preview",
            json={"candidate_id": candidate["id"]},
            headers=headers,
        )
        assert preview.status_code == 200
        admission = client.post(
            actual_path + "/decisions",
            json={
                "plan_id": preview.json()["id"],
                "decision_id": uuid4().hex,
                "reason": "실제 인증 API에서 준비된 고정 대상 교체를 승인함",
                "acknowledge": True,
            },
            headers=headers,
        )
        assert admission.status_code == 200 and admission.json()["phase"] == "planned"
        assert client.get(actual_path).json()["history"][0]["phase"] == "planned"
        assert executor.apply(admission.json()["id"])["phase"] == "applied"
        assert client.get(actual_path).json()["history"][0]["phase"] == "applied"
        assert len(calls) == 1
        member_password = secrets.token_urlsafe(28)
        assert (
            client.post(
                "/api/accounts",
                json={"username": "handover-member", "password": member_password},
                headers=headers,
            ).status_code
            == 201
        )
        login = client.post(
            "/api/auth/login",
            json={"username": "handover-member", "password": member_password},
        )
        assert client.get(path).status_code == 403
    disabled = create_app(
        db, allowed_origins=("http://testserver",), secure_cookies=False
    )
    assert not any(getattr(route, "path", "") == path for route in disabled.routes)
