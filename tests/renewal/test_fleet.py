"""Administrator access and real isolated CPU instance lifecycle/distribution."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from app.cpu_fleet import CpuProcesses
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_execution import admit, graph
from test_execution import movie as _movie_fixture
from test_foundation import admin as _admin_fixture
from test_foundation import db as _db_fixture
from test_foundation import login
from video_service.content_store import ContentStore
from video_service.postgres import Conflict
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.postgres.fleet import Fleet

admin = _admin_fixture
db = _db_fixture
movie = _movie_fixture


@pytest.fixture
def managed(db, tmp_path):
    store = ContentStore(tmp_path)
    driver = CpuProcesses(store)
    fleet = Fleet(db, driver)
    runtime = Execution(db, store, fleet=fleet)
    try:
        yield runtime, fleet, driver
    finally:
        fleet.close()


def activate(fleet, actor, kind="analyze", count=2):
    return fleet.configure(
        actor,
        kind,
        revision=fleet.get(kind)["revision"],
        enabled=count > 0,
        replicas=count,
    )


def seed(runtime, owner, movie):
    source = runtime.ingest(owner, "synthetic.mp4", movie)
    definition = runtime.save_definition(owner, uuid4().hex, graph("analyze"))
    return source, definition


def new_job(runtime, owner, source, definition):
    job = runtime.create(
        owner,
        source["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
    )
    admit(runtime, owner, job["id"])
    return job


def test_startup_readonly_and_real_start_scale_stop(managed, admin):
    runtime, fleet, driver = managed
    assert driver.processes == {}
    assert fleet.get("faceswap")["manageable"] is False
    assert fleet.get("analyze")["enabled"] is False
    assert driver.processes == {}
    active = activate(fleet, admin[0]["id"])
    assert active["state"] == "ready" and active["ready_replicas"] == 2
    pids = {i["pid"] for i in active["instances"] if i["state"] == "ready"}
    assert len(pids) == 2
    assert all(process.poll() is None for process in driver.processes.values())
    assert activate(fleet, admin[0]["id"], count=1)["ready_replicas"] == 1
    stopped = activate(fleet, admin[0]["id"], count=0)
    assert stopped["state"] == "stopped" and stopped["ready_replicas"] == 0
    assert all(process.poll() is not None for process in driver.processes.values())
    with runtime.database.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM agent_configuration_events"
            ).fetchone()["n"]
            == 3
        )


def test_parallel_jobs_routed_to_distinct_persistent_instances(managed, admin, movie):
    runtime, fleet, driver = managed
    owner = admin[0]["id"]
    activate(fleet, owner)
    source, definition = seed(runtime, owner, movie)
    jobs = [new_job(runtime, owner, source, definition) for _ in range(4)]
    for _ in range(4):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda j: runtime.run_local(owner, j["id"]), jobs))
        if all(runtime.get(owner, j["id"])["status"] == "completed" for j in jobs):
            break
    states = [runtime.get(owner, j["id"]) for j in jobs]
    assert all(j["status"] == "completed" for j in states)
    instances = {j["runs"][0]["agent_instance_id"] for j in states}
    assert len(instances) == 2
    assert all(j["runs"][0]["result"]["agent_instance_id"] in instances for j in states)
    assert len(driver.processes) == 2
    assert sum(i["completed"] for i in fleet.get("analyze")["instances"]) == 4


def test_disable_drains_claimed_work_and_blocks_new_assignments(managed, admin, movie):
    runtime, fleet, driver = managed
    owner = admin[0]["id"]
    activate(fleet, owner, count=1)
    source, definition = seed(runtime, owner, movie)
    job = new_job(runtime, owner, source, definition)
    second = new_job(runtime, owner, source, definition)
    command = runtime.claim_next(owner, job["id"])
    assert command
    stopped = activate(fleet, owner, count=0)
    assert stopped["state"] == "draining"
    assert runtime.claim_next(owner, second["id"]) is None
    assert next(iter(driver.processes.values())).poll() is None
    result = runtime.execute_command(owner, command)
    assert result["status"] == "completed"
    runtime.accept(owner, command, result)
    assert runtime.run_local(owner, job["id"])["status"] == "completed"
    assert fleet.get("analyze")["state"] == "stopped"
    assert next(iter(driver.processes.values())).poll() is not None
    assert runtime.get(owner, second["id"])["runs"] == []


def test_conflicts_limits_unavailable_runtime_and_wrong_actor(managed, admin):
    runtime, fleet, driver = managed
    owner = admin[0]["id"]
    user = Accounts(runtime.database).create("regular-fleet", admin[1], actor_id=owner)
    with pytest.raises(PermissionError):
        activate(fleet, user["id"])
    with pytest.raises(Conflict):
        activate(fleet, owner, kind="faceswap", count=1)
    assert driver.processes == {}
    activate(fleet, owner, count=1)
    with pytest.raises(Conflict):
        fleet.configure(owner, "analyze", revision=0, enabled=True, replicas=2)
    for kwargs in (
        {"enabled": True, "replicas": 0},
        {"enabled": False, "replicas": 1},
        {"enabled": True, "replicas": 9},
    ):
        with pytest.raises(ValueError):
            fleet.configure(owner, "analyze", revision=1, **kwargs)
    assert fleet.get("analyze")["ready_replicas"] == 1


def test_second_controller_cannot_adopt_or_duplicate_cpu_instances(managed, admin):
    runtime, fleet, driver = managed
    activate(fleet, admin[0]["id"], count=1)
    other = Fleet(runtime.database, CpuProcesses(runtime.store))
    try:
        with pytest.raises(Conflict):
            activate(other, admin[0]["id"], kind="encode", count=1)
        assert other.driver.processes == {}
        assert next(iter(driver.processes.values())).poll() is None
    finally:
        other.close()


def test_start_failure_and_actual_process_exit_are_not_reported_ready(
    managed, admin, tmp_path
):
    _, fleet, driver = managed
    original = driver.python
    driver.python = str(tmp_path / "not-an-installed-python")
    failed = activate(fleet, admin[0]["id"], count=1)
    assert failed["state"] == "degraded" and failed["ready_replicas"] == 0
    assert failed["instances"][0]["state"] == "failed"
    driver.python = original
    assert activate(fleet, admin[0]["id"], count=1)["ready_replicas"] == 1
    process = next(p for p in driver.processes.values() if p.poll() is None)
    process.terminate()
    process.wait(timeout=5)
    assert fleet.get("analyze")["ready_replicas"] == 0
    assert process.stdin.closed and process.stdout.closed


def test_database_failure_after_actual_ready_handshake_remains_controllable(
    managed, admin, monkeypatch
):
    runtime, fleet, driver = managed
    original = runtime.database.connection
    injected = False

    @contextmanager
    def connection():
        with original() as db:

            class Connection:
                def execute(self, statement, *args):
                    nonlocal injected
                    if "SET state='ready',pid=" in statement and not injected:
                        injected = True
                        raise psycopg.OperationalError(
                            "Injected test-only post-handshake write failure"
                        )
                    return db.execute(statement, *args)

            yield Connection()

    with monkeypatch.context() as patch:
        patch.setattr(runtime.database, "connection", connection)
        with pytest.raises(psycopg.OperationalError):
            activate(fleet, admin[0]["id"], count=1)
    assert injected
    process = next(iter(driver.processes.values()))
    assert process.poll() is None
    observed = fleet.get("analyze")
    assert (
        observed["ready_replicas"] == 1
        and observed["instances"][0]["pid"] == process.pid
    )
    assert activate(fleet, admin[0]["id"], count=0)["state"] == "stopped"
    assert process.poll() is not None


def test_all_administrative_apis_denied_but_regular_job_path_works(
    db, admin, tmp_path, movie
):
    store = ContentStore(tmp_path)
    seed_runtime = Execution(db, store)
    source, definition = seed(seed_runtime, admin[0]["id"], movie)
    user = Accounts(db).create("normal-user", admin[1], actor_id=admin[0]["id"])
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=store,
        local_execution=True,
    )
    with TestClient(app) as client:
        login(client, (user, admin[1]))
        admin_paths = [
            "/api/accounts",
            "/api/admin/agents",
            "/api/admin/agents/analyze",
            "/api/settings/node-catalog",
            "/api/settings/workflow-definitions",
            "/api/settings/workflow-definitions/" + definition["id"],
            "/api/settings/serving-connections",
            "/api/settings/registered-models",
        ]
        assert all(client.get(path).status_code == 403 for path in admin_paths)
        assert (
            client.put(
                "/api/admin/agents/analyze/configuration",
                json={"revision": 0, "enabled": True, "replicas": 1},
            ).status_code
            == 403
        )
        assert (
            client.put(
                "/api/settings/workflow-definitions/" + definition["id"],
                json=graph("analyze"),
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/settings/work-entry/inspect",
                json={"definition_id": definition["id"], "definition_revision": 1},
            ).status_code
            == 403
        )
        assert client.get("/api/videos/" + source["asset_id"]).status_code == 404
        assert (
            client.get("/api/work-entry/workflows").json()["definitions"][0]["id"]
            == definition["id"]
        )
        assert (
            client.get(
                "/api/work-entry/workflows/" + definition["id"] + "?revision=1"
            ).status_code
            == 200
        )
        own_source = seed_runtime.ingest(user["id"], "own.mp4", movie)
        selection = {
            "asset_id": own_source["asset_id"],
            "definition_id": definition["id"],
            "definition_revision": 1,
        }
        preview = client.post("/api/work-entry/preview", json=selection)
        assert preview.status_code == 200, preview.text
        created = client.post(
            "/api/work-entry/create",
            json={
                **selection,
                "token": preview.json()["token"],
                "request_id": uuid4().hex,
            },
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert (
            job["owner_id"] == user["id"] and job["workflow_owner_id"] == admin[0]["id"]
        )
        assert client.get("/api/jobs/" + job["id"]).status_code == 200
        assert (
            seed_runtime.get(user["id"], job["id"])["snapshot"]["definition"]
            == definition
        )


def test_api_configuration_csrf_revision_and_readback(db, admin, tmp_path):
    store = ContentStore(tmp_path)
    driver = CpuProcesses(store)
    with TestClient(
        create_app(
            db,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            content_store=store,
            local_execution=True,
            cpu_driver=driver,
        )
    ) as client:
        login(client, admin)
        url = "/api/admin/agents/analyze/configuration"
        assert (
            client.put(
                url,
                json={"revision": 0, "enabled": True, "replicas": 2},
                headers={"X-CSRF-Token": ""},
            ).status_code
            == 403
        )
        result = client.put(url, json={"revision": 0, "enabled": True, "replicas": 2})
        assert result.status_code == 200, result.text
        readback = client.get("/api/admin/agents/analyze").json()
        assert readback["revision"] == 1 and readback["ready_replicas"] == 2
        assert (
            client.put(
                url, json={"revision": 0, "enabled": False, "replicas": 0}
            ).status_code
            == 409
        )
        assert (
            client.put(
                url, json={"revision": 1, "enabled": False, "replicas": 0}
            ).status_code
            == 200
        )
        assert client.get("/api/admin/agents/analyze").json()["state"] == "stopped"
    assert all(process.poll() is not None for process in driver.processes.values())
