"""Scoped maintenance admission tests; no production DB or external transport."""

import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from app import server
from app.admission import AdmissionPolicy
from app.renewal import create_app
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.remote_control import RemoteControl


def test_server_never_opens_without_explicit_admission_policy(tmp_path, monkeypatch):
    dsn = tmp_path / "db.dsn"
    dsn.write_text("dbname=not_connected")
    content = tmp_path / "content"
    content.mkdir()
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
                "content_root": str(content),
                "allowed_origins": ["https://testserver"],
                "host": "127.0.0.1",
                "port": 8998,
                "secure_cookies": True,
            }
        )
    )
    monkeypatch.setattr("sys.argv", ["server", "--bootstrap-file", str(bootstrap)])
    import uvicorn

    opened = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: opened.append(True))
    try:
        server.main()
    except SystemExit as exc:
        assert exc.code == 2
    assert not opened, "listener opened without explicit admission requirement/config"


def test_maintenance_requirement_rejects_missing_config_before_runtime(
    tmp_path, monkeypatch
):
    dsn = tmp_path / "db.dsn"
    dsn.write_text("dbname=not_connected")
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
                "content_root": str(tmp_path),
                "allowed_origins": ["https://testserver"],
                "host": "127.0.0.1",
                "port": 8998,
                "secure_cookies": True,
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "server",
            "--bootstrap-file",
            str(bootstrap),
            "--admission-mode",
            "maintenance",
            "--enable-control",
        ],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("runtime entered with missing maintenance configuration")

    monkeypatch.setattr("app.operator.runtime_components", forbidden)
    try:
        server.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("missing policy did not close startup")


# Each schema is newly allocated on an explicitly isolated PG instance. No live
# DSN discovery, operating migrations, queue consumer or external model calls.


@pytest.fixture
def case18(tmp_path):
    assert os.environ.get("MIDEAGENT_MAINTENANCE_DISPOSABLE") == "1"
    root = Database(os.environ["MIDEAGENT_MAINTENANCE_TEST_DSN"])
    schema = "maintenance_" + uuid4().hex
    with root.connection() as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(make_conninfo(root.dsn, options="-c search_path=" + schema))
    from video_service import postgres

    with db.connection() as c:
        c.execute(
            "CREATE TABLE schema_migrations(name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for p in sorted((Path(postgres.__file__).parent / "migrations").glob("*.sql")):
            if p.name.startswith(("012_", "019_")):
                continue
            raw = p.read_bytes()
            c.execute(raw.decode())
            c.execute(
                "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
                (p.name, hashlib.sha256(raw).hexdigest()),
            )
    accounts = Accounts(db)
    password = secrets.token_urlsafe(28)
    admin = accounts.create("maintenance-admin", password, first=True)
    member_password = secrets.token_urlsafe(28)
    accounts.create("maintenance-member", member_password, actor_id=admin["id"])
    store = RemoteControl(db)
    slot = uuid4().hex
    store.provision("encode", "e" * 64, [slot])
    store.publish("encode", "e" * 64, [{"id": slot, "running": True, "state": "ready"}])
    policy = AdmissionPolicy(
        mode="maintenance", agent_id="encode", slot_id=slot, handover=False
    )
    yield db, store, policy, password, member_password
    with root.connection() as c:
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def maintenance_app(case, **kwargs):
    db, store, policy, *_ = case
    return create_app(
        db,
        allowed_origins=("https://testserver",),
        secure_cookies=True,
        remote_control=store,
        admission_policy=policy,
        **kwargs,
    )


def login(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return {
        "Origin": "https://testserver",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def test_existing_sessions_and_all_unclassified_methods_cannot_enter_handlers(
    case18, tmp_path
):
    db, _store, _policy, password, member_password = case18
    normal = create_app(
        db, allowed_origins=("https://testserver",), secure_cookies=True
    )
    maintenance = maintenance_app(case18)
    touched = tmp_path / "should-not-exist"

    @maintenance.get("/api/future-unclassified")
    def new_get():
        touched.write_text("unsafe GET entered")
        return {}

    denied = [
        ("POST", "/api/video-uploads"),
        ("PUT", "/api/video-uploads/" + "a" * 32 + "/chunks"),
        ("POST", "/api/video-uploads/" + "a" * 32 + "/complete"),
        ("PUT", "/api/source-metadata/" + "a" * 32),
        ("POST", "/api/jobs"),
        *[
            ("POST", "/api/jobs/" + "a" * 32 + "/" + p)
            for p in ["confirm", "admit", "run", "cancel"]
        ],
        ("POST", "/api/accounts"),
        ("PUT", "/api/settings/serving-connections/" + "a" * 32),
        ("POST", "/api/admin/processing-review/" + "a" * 32 + "/decisions"),
        ("POST", "/api/admin/agents/encode/recovery/decisions"),
        ("GET", "/api/jobs"),
        ("GET", "/api/capabilities"),
        ("GET", "/api/future-unclassified"),
        ("HEAD", "/api/future-unclassified"),
        ("OPTIONS", "/anything"),
        ("POST", "/api/auth/bootstrap"),
        ("GET", "/openapi.json"),
    ]
    for user, secret in [
        ("maintenance-admin", password),
        ("maintenance-member", member_password),
    ]:
        with (
            TestClient(normal, base_url="https://testserver") as old,
            TestClient(maintenance, base_url="https://testserver") as current,
        ):
            headers = login(old, user, secret)
            current.cookies.update(old.cookies)
            assert current.get("/api/auth/session").json()["user"]["username"] == user
            with db.connection() as c:
                before = {
                    n: c.execute(
                        sql.SQL("SELECT count(*) AS n FROM {}").format(
                            sql.Identifier(n)
                        )
                    ).fetchone()["n"]
                    for n in [
                        "jobs",
                        "assets",
                        "remote_control_requests",
                        "model_revisions",
                        "connection_revisions",
                        "accounts",
                    ]
                }
            for method, path in denied:
                h = {
                    **headers,
                    "Content-Type": "application/octet-stream"
                    if path.endswith("/chunks")
                    else "application/json",
                }
                response = current.request(
                    method, path, content=b"forbidden-body", headers=h
                )
                assert response.status_code == 503, (
                    user,
                    method,
                    path,
                    response.status_code,
                )
                if method != "HEAD":
                    assert response.json()["detail"] == "maintenance_admission_closed"
            with db.connection() as c:
                after = {
                    n: c.execute(
                        sql.SQL("SELECT count(*) AS n FROM {}").format(
                            sql.Identifier(n)
                        )
                    ).fetchone()["n"]
                    for n in before
                }
            assert after == before
            assert not touched.exists()


def test_maintenance_never_admits_start_or_other_slot(case18):
    db, _store, _policy, password, _ = case18
    with TestClient(maintenance_app(case18), base_url="https://testserver") as client:
        headers = login(client, "maintenance-admin", password)
        for enabled, replicas in [(True, 1), (True, 2)]:
            response = client.put(
                "/api/admin/agents/encode/configuration",
                headers=headers,
                json={
                    "revision": 0,
                    "enabled": enabled,
                    "replicas": replicas,
                    "request_id": uuid4().hex,
                },
            )
            assert response.status_code == 503
        assert (
            client.put(
                "/api/admin/agents/analyze/configuration",
                headers=headers,
                json={
                    "revision": 0,
                    "enabled": False,
                    "replicas": 0,
                    "request_id": uuid4().hex,
                },
            ).status_code
            == 503
        )
        with db.connection() as c:
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM remote_control_requests"
                ).fetchone()["n"]
                == 0
            )


def test_allowed_auth_query_stop0_keep_security_and_revision(case18):
    _db, _store, _policy, password, member_password = case18
    with TestClient(maintenance_app(case18), base_url="https://testserver") as client:
        endpoint = "/api/admin/agents/encode/configuration"
        body = {
            "revision": 0,
            "enabled": False,
            "replicas": 0,
            "request_id": uuid4().hex,
        }
        assert client.get("/api/admin/agents/encode").status_code == 401
        headers = login(client, "maintenance-member", member_password)
        assert client.get("/api/admin/agents/encode").status_code == 403
        assert client.put(endpoint, json=body, headers=headers).status_code == 403
        headers = login(client, "maintenance-admin", password)
        assert client.get("/api/admin/agents/encode").status_code == 200
        assert client.put(endpoint, json=body).status_code == 403
        assert (
            client.put(
                endpoint,
                json=body,
                headers={**headers, "Origin": "https://other.invalid"},
            ).status_code
            == 403
        )
        assert (
            client.put(
                endpoint, json={**body, "container_id": "a" * 64}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.put(
                endpoint, json={**body, "revision": 123}, headers=headers
            ).status_code
            == 409
        )
        stop = client.put(endpoint, json=body, headers=headers)
        assert stop.status_code == 200 and stop.json()["phase"] == "queued"
        assert client.put(endpoint, json=body, headers=headers).json() == stop.json()
        assert client.post("/api/auth/logout").status_code == 403
        assert client.post("/api/auth/logout", headers=headers).status_code == 204
        assert client.get("/api/auth/session").json()["user"] is None


def test_bound_slot_changed_after_startup_cannot_be_stopped(case18):
    db, _store, _policy, password, _ = case18
    app = maintenance_app(case18)
    with db.connection() as c:
        c.execute(
            "UPDATE remote_control_groups SET slot_ids=%s WHERE agent_id='encode'",
            (json.dumps([uuid4().hex]),),
        )
    with TestClient(app, base_url="https://testserver") as client:
        headers = login(client, "maintenance-admin", password)
        response = client.put(
            "/api/admin/agents/encode/configuration",
            headers=headers,
            json={
                "revision": 0,
                "enabled": False,
                "replicas": 0,
                "request_id": uuid4().hex,
            },
        )
        assert response.status_code == 409
        with db.connection() as c:
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM remote_control_requests"
                ).fetchone()["n"]
                == 0
            )


def test_server_maintenance_skips_storage_credentials_broker_startup(
    tmp_path, monkeypatch
):
    dsn = tmp_path / "db.dsn"
    dsn.write_text("dbname=not_connected")
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
                "content_root": str(tmp_path / "must-not-create"),
                "allowed_origins": ["https://testserver"],
                "host": "127.0.0.1",
                "port": 8998,
                "secure_cookies": True,
                "admission_policy": {
                    "mode": "maintenance",
                    "agent_id": "encode",
                    "slot_id": "a" * 32,
                    "handover": False,
                },
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "server",
            "--bootstrap-file",
            str(bootstrap),
            "--admission-mode",
            "maintenance",
            "--enable-control",
        ],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "maintenance touched storage/credential/broker initializer"
        )

    monkeypatch.setattr("app.operator.runtime_components", forbidden)
    seen = []
    from fastapi import FastAPI

    def construct(*args, **kwargs):
        seen.append(kwargs)
        return FastAPI()

    monkeypatch.setattr("app.renewal.create_app", construct)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    server.main()
    assert len(seen) == 1 and seen[0]["content_store"] is None
    assert seen[0]["admission_policy"].mode == "maintenance"
    assert seen[0]["target_handover"] is None
    assert not (tmp_path / "must-not-create").exists()


def test_existing_narrow_api_permissions_are_sufficient_for_018_query_stop(case18):
    db, _store, policy, password, _ = case18
    role = "maint_api_" + uuid4().hex
    with db.connection() as c:
        schema = c.execute("SELECT current_schema() AS s").fetchone()["s"]
        c.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role))
        )
        c.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        for grant in [
            "SELECT ON accounts,sessions,login_limits,remote_control_groups,remote_control_requests",
            "UPDATE(active,role) ON accounts",
            "INSERT,UPDATE,DELETE ON sessions,login_limits",
            "INSERT ON remote_control_requests",
            "UPDATE(revision,enabled,replicas,pending_request) ON remote_control_groups",
        ]:
            c.execute(sql.SQL("GRANT " + grant + " TO {}").format(sql.Identifier(role)))
    limited = Database(make_conninfo(db.dsn, user=role))
    app = create_app(
        limited,
        allowed_origins=("https://testserver",),
        secure_cookies=True,
        remote_control=RemoteControl(limited),
        admission_policy=policy,
    )
    with TestClient(app, base_url="https://testserver") as client:
        headers = login(client, "maintenance-admin", password)
        assert client.get("/api/admin/agents/encode").status_code == 200
        assert (
            client.put(
                "/api/admin/agents/encode/configuration",
                headers=headers,
                json={
                    "revision": 0,
                    "enabled": False,
                    "replicas": 0,
                    "request_id": uuid4().hex,
                },
            ).status_code
            == 200
        )
    with limited.connection() as c:
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'jobs','INSERT') AS p"
        ).fetchone()["p"]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'schema_migrations','SELECT') AS p"
        ).fetchone()["p"]


def test_blocked_binary_and_unclassified_get_do_not_read_body_or_touch_db(
    case18, monkeypatch
):
    import asyncio

    db, *_ = case18
    app = maintenance_app(case18)

    def forbidden(*args, **kwargs):
        raise AssertionError("blocked request entered database or body receive")

    monkeypatch.setattr(db, "connection", forbidden)

    async def exercise(method, path):
        sent = []

        async def receive():
            forbidden()

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": method,
                "scheme": "https",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "server": ("testserver", 443),
                "client": ("127.0.0.1", 1234),
                "headers": [
                    (b"host", b"testserver"),
                    (b"origin", b"https://testserver"),
                    (b"content-type", b"application/octet-stream"),
                ],
            },
            receive,
            send,
        )
        assert (
            next(m["status"] for m in sent if m["type"] == "http.response.start") == 503
        )

    asyncio.run(exercise("PUT", "/api/video-uploads/" + "a" * 32 + "/chunks"))
    asyncio.run(exercise("GET", "/api/unknown-read-with-side-effect"))


def test_019_gate_requires_explicit_phase_and_matching_injection(case18):
    from dataclasses import replace

    from video_service import postgres
    from video_service.postgres.target_handover import TargetHandover

    db, store, policy, *_ = case18
    app18 = maintenance_app(case18)
    policy19 = replace(policy, handover=True)
    with pytest.raises(ValueError, match="requires_schema_019"):
        create_app(
            db,
            allowed_origins=("https://testserver",),
            remote_control=store,
            admission_policy=policy19,
            target_handover=TargetHandover(store),
        )
    raw = (
        Path(postgres.__file__).parent / "migrations/019_target_handover.sql"
    ).read_bytes()
    with db.connection() as c:
        c.execute(raw.decode())
        c.execute(
            "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
            ("019_target_handover.sql", hashlib.sha256(raw).hexdigest()),
        )
    for app in [app18, maintenance_app(case18)]:
        with TestClient(app, base_url="https://testserver") as client:
            assert (
                client.get("/api/admin/agents/encode/target-handover").status_code
                == 503
            )
            assert (
                client.post(
                    "/api/admin/agents/encode/target-handover/preview", json={}
                ).status_code
                == 503
            )
    with pytest.raises(ValueError, match="requires_target_handover"):
        create_app(
            db,
            allowed_origins=("https://testserver",),
            remote_control=store,
            admission_policy=policy19,
        )


def test_maintenance_019_allows_actual_admin_preview_and_decision_only(
    case18, tmp_path
):
    from test_target_handover import setup_case
    from video_service import postgres
    from video_service.postgres.target_handover import TargetHandover
    from video_service.target_handover import HandoverHost

    db, _, _, password, member_password = case18
    raw = (
        Path(postgres.__file__).parent / "migrations/019_target_handover.sql"
    ).read_bytes()
    with db.connection() as c:
        c.execute(raw.decode())
        c.execute(
            "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
            ("019_target_handover.sql", hashlib.sha256(raw).hexdigest()),
        )
        admin = c.execute(
            "SELECT id FROM accounts WHERE username='maintenance-admin'"
        ).fetchone()["id"]
    state = setup_case((db, admin), tmp_path)
    _, _, store, group, slot, old, new, receipts, signals, *_ = state
    ledger = TargetHandover(store)
    host = HandoverHost(ledger, old, new, {group: [slot]}, receipts)
    candidate = host.prepare(group)
    policy = AdmissionPolicy(
        mode="maintenance", agent_id=group, slot_id=slot, handover=True
    )
    app = create_app(
        db,
        allowed_origins=("https://testserver",),
        remote_control=store,
        target_handover=ledger,
        admission_policy=policy,
    )
    root = "/api/admin/agents/" + group + "/target-handover"
    with TestClient(app, base_url="https://testserver") as client:
        headers = login(client, "maintenance-member", member_password)
        assert (
            client.post(
                root + "/preview",
                json={"candidate_id": candidate["id"]},
                headers=headers,
            ).status_code
            == 403
        )
        headers = login(client, "maintenance-admin", password)
        assert (
            client.post(
                root + "/preview", json={"candidate_id": candidate["id"]}
            ).status_code
            == 403
        )
        assert client.post("/api/jobs", json={}, headers=headers).status_code == 503
        preview = client.post(
            root + "/preview", json={"candidate_id": candidate["id"]}, headers=headers
        )
        assert preview.status_code == 200
        decision = {
            "plan_id": preview.json()["id"],
            "decision_id": uuid4().hex,
            "reason": "유지보수 모드의 정상 인증 관리자 전환 승인",
            "acknowledge": True,
        }
        assert (
            client.post(
                root + "/decisions", json={**decision, "reason": "x"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                root + "/decisions",
                json={**decision, "acknowledge": False},
                headers=headers,
            ).status_code
            == 422
        )
        accepted = client.post(root + "/decisions", json=decision, headers=headers)
        assert accepted.status_code == 200 and accepted.json()["phase"] == "planned"
        assert host.apply(accepted.json()["id"])["phase"] == "applied"
        assert client.get(root).json()["history"][0]["phase"] == "applied"
        assert (
            client.put(
                "/api/admin/agents/" + group + "/configuration",
                json={
                    "revision": 0,
                    "enabled": True,
                    "replicas": 1,
                    "request_id": uuid4().hex,
                },
                headers=headers,
            ).status_code
            == 503
        )
    assert len(signals) == 1


@pytest.mark.parametrize(
    "change,mode,extra",
    [
        ({"admission_policy": {"mode": "normal"}}, "maintenance", ["--enable-control"]),
        ({}, "normal", ["--enable-control"]),
        ({}, "maintenance", []),
        ({}, "maintenance", ["--enable-control", "--enable-broker"]),
        ({"secure_cookies": False}, "maintenance", ["--enable-control"]),
        (
            {"allowed_origins": ["http://testserver"]},
            "maintenance",
            ["--enable-control"],
        ),
        (
            {
                "admission_policy": {
                    "mode": "maintenance",
                    "agent_id": "encode",
                    "slot_id": "a" * 32,
                    "handover": "false",
                }
            },
            "maintenance",
            ["--enable-control"],
        ),
    ],
)
def test_startup_mode_mismatch_or_unsafe_security_never_enters_runtime(
    tmp_path, monkeypatch, change, mode, extra
):
    dsn = tmp_path / "db.dsn"
    dsn.write_text("dbname=not_connected")
    config = {
        "database_dsn_file": str(dsn),
        "content_root": str(tmp_path),
        "allowed_origins": ["https://testserver"],
        "host": "127.0.0.1",
        "port": 8998,
        "secure_cookies": True,
        "admission_policy": {
            "mode": "maintenance",
            "agent_id": "encode",
            "slot_id": "a" * 32,
            "handover": False,
        },
    }
    config.update(change)
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(json.dumps(config))
    monkeypatch.setattr(
        "sys.argv",
        [
            "server",
            "--bootstrap-file",
            str(bootstrap),
            "--admission-mode",
            mode,
            *extra,
        ],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("bad startup reached runtime/listener")

    monkeypatch.setattr("app.operator.runtime_components", forbidden)
    monkeypatch.setattr("uvicorn.run", forbidden)
    with pytest.raises(SystemExit) as out:
        server.main()
    assert out.value.code == 2


def test_preflight_failure_does_not_open_listener_or_log_private_detail(
    tmp_path, monkeypatch, capsys
):
    dsn = tmp_path / "db.dsn"
    dsn.write_text("dbname=not_connected")
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
                "content_root": str(tmp_path),
                "allowed_origins": ["https://testserver"],
                "host": "127.0.0.1",
                "port": 8998,
                "secure_cookies": True,
                "admission_policy": {
                    "mode": "maintenance",
                    "agent_id": "encode",
                    "slot_id": "a" * 32,
                    "handover": False,
                },
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "server",
            "--bootstrap-file",
            str(bootstrap),
            "--admission-mode",
            "maintenance",
            "--enable-control",
        ],
    )

    def fail(*args, **kwargs):
        raise ValueError("private-startup-detail-must-not-be-logged")

    monkeypatch.setattr("app.renewal.create_app", fail)
    with pytest.raises(SystemExit) as out:
        server.main()
    assert out.value.code == 2
    assert "private-startup-detail-must-not-be-logged" not in capsys.readouterr().err
