"""Disposable PostgreSQL worker-status persistence; no operating schema writes."""
import importlib
from uuid import uuid4

from test_foundation import db as db  # explicit disposable test fixture


def test_worker_state_sequence_expiry_and_new_boot_fence(db):
    module = "video_service.postgres.worker_telemetry"
    assert importlib.util.find_spec(module) is not None, "telemetry persistence missing"
    Store = importlib.import_module(module).WorkerTelemetry
    store = Store(db)
    wid = uuid4().hex
    value = {"version": 1, "worker_id": wid, "boot_id": "1" * 32, "family": "cpu", "role": "analyze",
             "state": "connected", "sequence": 0, "ticket_id": None, "attempt_id": None}
    ex = "mideagent.telemetry.cpu.analyze.v1"
    accept = lambda r: store.accept(r, ex, expected_worker_id=wid)
    assert accept(value)
    store.beat()
    assert store.role("analyze")["workers"][0]["state"] == "connected"
    ready = {**value, "state": "ready", "sequence": 1}
    assert accept(ready) and not accept(ready)
    with db.connection() as connection:
        connection.execute("UPDATE worker_observations SET received_at=now()-interval '20 seconds'")
    assert store.role("analyze")["workers"][0]["state"] == "heartbeat_lost"
    fresh = {**ready, "boot_id": "2" * 32, "sequence": 3}
    assert accept(fresh)
    assert not accept({**ready, "sequence": 999})
    assert store.role("analyze")["workers"][0]["state"] == "ready"
    with db.connection() as connection:
        connection.execute("UPDATE telemetry_observer SET received_at=now()-interval '20 seconds'")
    assert not store.role("analyze")["collector"]["healthy"]


def test_api_and_list_use_worker_telemetry_without_broker_inspection(db):
    from types import SimpleNamespace
    from app.renewal import create_app
    from video_service.postgres.broker_fleet import BrokerFleet
    from video_service.postgres.worker_telemetry import WorkerTelemetry
    from fastapi.testclient import TestClient
    from video_service.postgres.accounts import Accounts
    import secrets

    store = WorkerTelemetry(db)
    wid = uuid4().hex
    value = {"version": 1, "worker_id": wid, "boot_id": "1" * 32, "family": "cpu", "role": "analyze",
             "state": "ready", "sequence": 1, "ticket_id": None, "attempt_id": None}
    store.accept(value, "mideagent.telemetry.cpu.analyze.v1", expected_worker_id=wid)
    store.beat()
    def forbidden_factory():
        raise AssertionError("API must not inspect queues with controller credentials")
    fleet = BrokerFleet(db, forbidden_factory, telemetry=store)
    assert fleet.get("analyze")["state"] == "ready"
    app = create_app(db, allowed_origins=("http://testserver",), secure_cookies=False,
                     local_execution=True, content_store=SimpleNamespace(storage_kind="s3"), broker_factory=forbidden_factory)
    password = secrets.token_urlsafe(24)
    Accounts(db).create("status-only-fixture", password, first=True)
    with TestClient(app) as client:
        assert client.get("/api/admin/agents/analyze").status_code == 401
        assert client.post("/api/auth/login", json={"username": "status-only-fixture", "password": password}).status_code == 200
        detail = client.get("/api/admin/agents/analyze").json()
        listed = next(x for x in client.get("/api/admin/agents").json()["agents"] if x["agent_id"] == "analyze")
        assert detail["state"] == listed["state"] == "ready"
        assert detail["workers"][0]["worker_id"] == wid
