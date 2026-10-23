"""Opt-in isolated PG/TLS S3 + installed-code tests. No operating media or provider."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from test_execution import graph
from video_service.cpu_agents import probe
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.transport_files import object_store


@pytest.fixture(scope="module")
def large():
    root = os.environ.get("LARGE_CPU_BOOTSTRAP")
    if not root:
        pytest.skip("Explicit isolated large CPU stack is required")
    assert os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
    root = Path(root)
    dsn = (root / "dsn").read_text()
    target = conninfo_to_dict(dsn)
    assert target["host"] == "registered-db" and target["dbname"] == "large_cpu_fixture"
    schema = "large_cpu_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(make_conninfo(dsn, options="-c search_path=" + schema))
    db.migrate()
    secret = json.loads((root / "fixture.json").read_text())
    accounts = Accounts(db)
    owner = accounts.create(
        "large-preservation-actor", secret["login_password"], first=True
    )
    actor = accounts.create(
        "large-execution-actor", secret["login_password"], actor_id=owner["id"]
    )
    store = object_store(root / "seed-objects.json")
    try:
        store.client.create_bucket(Bucket=store.bucket)
    except store.client.exceptions.BucketAlreadyOwnedByYou:
        pass
    source = Path("/media/large-synthetic.mov")
    ref = store.import_original_file(
        owner["id"],
        source,
        sha256=secret["source_sha256"],
        byte_count=secret["source_bytes"],
    )
    assert source.stat().st_size > 256 * 1024 * 1024
    asset = uuid4().hex
    media = probe(source)
    with db.connection() as connection:
        connection.execute(
            "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                owner["id"],
                asset,
                "large-synthetic.mov",
                "sha256:" + ref["sha256"],
                ref["bytes"],
                ref["sha256"],
                Jsonb(
                    {
                        "registration_state": "verified",
                        "media": media,
                        "legacy_origin": {
                            "original_owner_id": None,
                            "imported_by": owner["id"],
                            "namespace": "fixture-only",
                        },
                    }
                ),
            ),
        )
    runtime = Execution(db, store)
    definition = uuid4().hex
    runtime.save_definition(owner["id"], definition, graph("encode", "validate_video"))
    yield SimpleNamespace(
        database=db,
        runtime=runtime,
        owner=owner["id"],
        actor=actor["id"],
        asset=asset,
        definition=definition,
        root=root,
        store=store,
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
        )


def test_large_ticket_freezes_cpu_policy_and_keeps_unknown_uploader(large):
    value = large.runtime.create(
        large.actor, large.asset, large.definition, 1, request_id=uuid4().hex
    )
    assert value["status"] == "draft"
    assert value["snapshot"]["cpu_input_policy"]["agent_revision"] == "2"
    assert value["asset_owner_id"] == large.owner
    assert value["snapshot"]["asset"]["original_uploaded_by"] is None
    assert (
        large.runtime.shared_get(large.actor, value["id"])["snapshot"]["asset"][
            "uploaded_by"
        ]
        is None
    )
    assert value["snapshot"]["inputs"]["video"]["source_owner_id"] == large.owner


def test_admitted_large_ticket_emits_v2_and_bounded_matching_lease(large):
    from test_execution import admit

    value = large.runtime.create(
        large.actor, large.asset, large.definition, 1, request_id=uuid4().hex
    )
    admit(large.runtime, large.actor, value["id"])
    request = large.runtime.claim_next(large.actor, value["id"])
    assert request["agent"] == {"id": "encode", "revision": "2"}
    with large.database.connection() as connection:
        row = connection.execute(
            "SELECT agent_revision,extract(epoch from lease_expires_at-now()) AS remaining FROM node_runs WHERE id=%s",
            (request["attempt_id"],),
        ).fetchone()
    assert row["agent_revision"] == "2" and 9000 < row["remaining"] <= 9600


@pytest.fixture(scope="module")
def installed(large):
    import shutil
    import signal
    import subprocess
    import sys
    import time

    import httpx

    private = Path("/cache") / ("installed-" + uuid4().hex)
    private.mkdir()
    for file in large.root.iterdir():
        if file.is_file():
            shutil.copyfile(file, private / file.name)
    (private / "dsn").write_text(large.database.dsn)
    for role in ("api", "results"):
        cfg = json.loads((private / (role + ".json")).read_text())
        cfg["database_dsn_file"] = str(private / "dsn")
        (private / (role + ".json")).write_text(json.dumps(cfg))
    processes = []
    handles = []
    for name, module, args in [
        ("results", "app.operator", ["consume-results"]),
        ("api", "app.server", ["--admission-mode", "normal"]),
    ]:
        handle = (private / (name + ".log")).open("wb")
        handles.append(handle)
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    module,
                    *args,
                    "--bootstrap-file",
                    str(private / (name + ".json")),
                    "--enable-broker",
                ],
                stdout=handle,
                stderr=subprocess.STDOUT,
                env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            )
        )
    client = httpx.Client(
        base_url="http://127.0.0.1:9418",
        headers={"Origin": "http://127.0.0.1:9418"},
        timeout=90,
        trust_env=False,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if client.get("/healthz").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("Installed API not ready; private logs retained")
        password = json.loads((large.root / "fixture.json").read_text())[
            "login_password"
        ]
        reply = client.post(
            "/api/auth/login",
            json={"username": "large-execution-actor", "password": password},
        )
        assert reply.status_code == 200
        client.headers["X-CSRF-Token"] = reply.json()["csrf_token"]
        yield SimpleNamespace(client=client, private=private)
    finally:
        client.close()
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process in processes:
            process.wait(timeout=30)
        for handle in handles:
            handle.close()


def make_http_ticket(large, installed):
    client = installed.client
    selection = {
        "asset_id": large.asset,
        "definition_id": large.definition,
        "definition_revision": 1,
        "recovery_enabled": False,
        "options": {},
    }
    preview = client.post("/api/work-entry/preview", json=selection)
    assert preview.status_code == 200, preview.text
    assert preview.json()["cpu_input_policy"]["agent_revision"] == "2"
    made = client.post(
        "/api/work-entry/create",
        json={**selection, "token": preview.json()["token"], "request_id": uuid4().hex},
    )
    assert made.status_code == 201, made.text
    identity = made.json()["id"]
    plan = client.get("/api/renewal/jobs/" + identity + "/plan")
    assert plan.status_code == 200
    consent = client.post(
        "/api/renewal/jobs/" + identity + "/confirm",
        json={"token": plan.json()["token"], "request_id": uuid4().hex},
    )
    assert consent.status_code == 200, consent.text
    admitted = client.post(
        "/api/renewal/jobs/" + identity + "/admit",
        json={"consent_id": consent.json()["id"], "request_id": uuid4().hex},
    )
    assert admitted.status_code == 200, admitted.text
    return identity


def test_installed_large_http_to_real_cpu_and_ticket_download(large, installed):
    import time

    from video_service.cpu_agents import digest

    identity = make_http_ticket(large, installed)
    sent = installed.client.post("/api/renewal/jobs/" + identity + "/run", json={})
    assert sent.status_code == 200, sent.text
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        response = installed.client.get("/api/renewal/jobs/" + identity)
        assert response.status_code == 200
        state = response.json()
        if state["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    assert state["status"] == "completed", {
        "status": state["status"],
        "runs": [(r["node_type"], r["status"], r["error_code"]) for r in state["runs"]],
    }
    assert len(state["runs"]) == 2
    actual = []
    with large.database.connection() as connection:
        rows = connection.execute(
            "SELECT request,request_sha256,result FROM node_runs WHERE job_id=%s",
            (identity,),
        ).fetchall()
    for row in rows:
        assert row["request"]["agent"]["revision"] == "2"
        assert digest(row["request"]) == row["request_sha256"]
    for run in state["runs"]:
        for port, reference in run["result"]["outputs"].items():
            reply = installed.client.get(
                "/api/renewal/jobs/" + identity + "/artifacts/" + run["id"] + "/" + port
            )
            assert reply.status_code == 200
            sha = hashlib.sha256(reply.content).hexdigest()
            assert (
                sha == reference["sha256"] and len(reply.content) == reference["bytes"]
            )
            actual.append(
                {
                    "node": run["node_type"],
                    "port": port,
                    "bytes": len(reply.content),
                    "sha256": sha,
                }
            )
    manifest = installed.client.get("/api/renewal/jobs/" + identity + "/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["uploaded_by"] is None
    evidence = {
        "job": identity,
        "status": state["status"],
        "source_bytes": 311040938,
        "cpu_policy": state["snapshot"]["cpu_input_policy"],
        "downloaded": actual,
        "manifest": manifest.json(),
        "independent_api_results_and_two_cpu_consumers": True,
    }
    Path("/evidence/large-cpu-success.json").write_text(json.dumps(evidence, indent=2))


def test_large_call_cancel_has_no_followup_and_late_result_is_quarantined(
    large, installed
):
    import time

    identity = make_http_ticket(large, installed)
    response = installed.client.post("/api/renewal/jobs/" + identity + "/run", json={})
    assert response.status_code == 200, response.text
    latest = installed.client.get("/api/renewal/jobs/" + identity)
    assert latest.status_code == 200
    revision = latest.json()["revision"]
    cancelled = installed.client.post(
        "/api/renewal/jobs/" + identity + "/cancel", json={"revision": revision}
    )
    assert cancelled.status_code == 200, cancelled.text
    deadline = time.monotonic() + 150
    observed = None
    while time.monotonic() < deadline:
        with large.database.connection() as connection:
            observed = connection.execute(
                "SELECT (SELECT count(*) FROM result_quarantine WHERE job_id=%s) AS late,(SELECT count(*) FROM artifacts WHERE job_id=%s) AS artifacts,(SELECT count(*) FROM node_runs WHERE job_id=%s AND node_type='validate_video') AS followup",
                (identity, identity, identity),
            ).fetchone()
        if observed["late"]:
            break
        time.sleep(0.2)
    assert (
        observed["late"] == 1
        and observed["artifacts"] == 0
        and observed["followup"] == 0
    )
    final = installed.client.get("/api/renewal/jobs/" + identity)
    assert final.status_code == 200 and final.json()["status"] == "cancelled"
    with large.database.connection() as connection:
        runs = connection.execute(
            "SELECT node_type,status,request FROM node_runs WHERE job_id=%s",
            (identity,),
        ).fetchall()
    assert len(runs) == 1 and runs[0]["request"]["agent"]["revision"] == "2"
    Path("/evidence/large-cpu-cancel.json").write_text(
        json.dumps(
            {
                "job": identity,
                "status": "cancelled",
                "cancel_posts": 1,
                "late_quarantine": observed["late"],
                "normal_artifacts": 0,
                "followup_calls": 0,
                "source_bytes": 311040938,
                "run_status": runs[0]["status"],
            },
            indent=2,
        )
    )


def test_large_ticket_cannot_use_api_local_execution(large, monkeypatch):
    from video_service.postgres import Conflict

    value = large.runtime.create(
        large.actor, large.asset, large.definition, 1, request_id=uuid4().hex
    )

    def forbidden(*_):
        raise AssertionError("CPU processing must not run inside the API")

    monkeypatch.setattr(large.runtime, "execute_command", forbidden)
    with pytest.raises(Conflict, match="broker"):
        large.runtime.run_local(large.actor, value["id"])


def test_source_verification_does_not_block_reads_or_cancel_and_rechecks_state(
    large, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    value = large.runtime.create(
        large.actor, large.asset, large.definition, 1, request_id=uuid4().hex
    )
    entered, released = threading.Event(), threading.Event()
    original = large.store.path

    def verified_path(owner, reference):
        if reference["bytes"] > 256 * 1024 * 1024:
            entered.set()
            assert released.wait(15)
        return original(owner, reference)

    monkeypatch.setattr(large.store, "path", verified_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(large.runtime.plan, large.actor, value["id"])
        try:
            assert entered.wait(10)
            # A real second PG session must not wait on the verifier's job lock.
            observed = large.runtime.shared_get(large.actor, value["id"])
            cancelled = large.runtime.cancel(
                large.actor, value["id"], observed["revision"]
            )
            assert cancelled["status"] == "cancelled"
        finally:
            released.set()
        plan = future.result(timeout=30)
        assert plan["ready"] is False
    with large.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM execution_consents WHERE job_id=%s",
                (value["id"],),
            ).fetchone()["n"]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM node_runs WHERE job_id=%s", (value["id"],)
            ).fetchone()["n"]
            == 0
        )


def test_oversize_and_other_role_rejected_before_fetch_or_ticket_insert(
    large, monkeypatch
):
    oversized = uuid4().hex
    with large.database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM assets WHERE id=%s", (large.asset,)
        ).fetchone()
        connection.execute(
            "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                large.owner,
                oversized,
                "rejection-reference-only.mov",
                row["storage_key"],
                4 * 1024 * 1024 * 1024 + 1,
                row["sha256"],
                Jsonb(row["metadata"]),
            ),
        )
        before = connection.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
    other = uuid4().hex
    large.runtime.save_definition(large.owner, other, graph("extract_audio"))

    def no_fetch(*_):
        raise AssertionError("Unsupported input must be rejected before storage I/O")

    monkeypatch.setattr(large.store, "path", no_fetch)
    with pytest.raises(ValueError, match="4 GiB"):
        large.runtime.create(
            large.actor, oversized, large.definition, 1, request_id=uuid4().hex
        )
    with pytest.raises(ValueError, match="only"):
        large.runtime.create(large.actor, large.asset, other, 1, request_id=uuid4().hex)
    with large.database.connection() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
            == before
        )
