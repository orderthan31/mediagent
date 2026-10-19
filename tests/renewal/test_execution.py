"""Real isolated PG/content/process tests. No operational settings or network model."""

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from test_foundation import admin as _admin_fixture
from test_foundation import db as _db_fixture
from test_foundation import login
from video_service.content_store import ContentStore
from video_service.postgres import Conflict, Missing
from video_service.postgres.execution import Execution

# Register imported pytest fixtures without shadowing unused imports.
admin = _admin_fixture
db = _db_fixture


@pytest.fixture
def runtime(db, tmp_path):
    return Execution(db, ContentStore(tmp_path))


@pytest.fixture
def movie(tmp_path):
    target = tmp_path / "synthetic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=5:d=0.6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=0.6",
            "-threads",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return target.read_bytes()


def graph(*types):
    nodes, edges = [], []
    previous = "$input"
    port = "video"
    for index, kind in enumerate(types):
        identity = "n" + str(index)
        options = (
            {"subtitle_mode": "none"}
            if kind == "encode"
            else {"data_type": "video"}
            if kind == "review"
            else {}
        )
        nodes.append(
            {
                "id": identity,
                "type": kind,
                "position": {"x": 300 * index, "y": 50},
                "options": options,
            }
        )
        incoming = "value" if kind == "review" else "video"
        edges.append(
            {
                "id": "e" + str(index),
                "source": {"node": previous, "port": port},
                "target": {"node": identity, "port": incoming},
            }
        )
        previous, port = (
            identity,
            (
                "value"
                if kind == "review"
                else "metadata"
                if kind == "analyze"
                else "report"
                if kind == "validate_video"
                else "video"
            ),
        )
    return {
        "catalog_version": 1,
        "revision": 0,
        "name": "CPU 검증",
        "inputs": {"video": "video"},
        "nodes": nodes,
        "edges": edges,
    }


def setup(runtime, owner, movie, definition=None):
    source = runtime.ingest(owner, "synthetic.mp4", movie)
    identity = uuid4().hex
    saved = runtime.save_definition(
        owner, identity, definition or graph("encode", "validate_video")
    )
    job = runtime.create(
        owner, source["asset_id"], identity, saved["revision"], request_id=uuid4().hex
    )
    return source, saved, job


def admit(runtime, owner, identity):
    plan = runtime.plan(owner, identity)
    consent = runtime.confirm(owner, identity, plan["token"], uuid4().hex)
    return runtime.admit(owner, identity, consent["id"], uuid4().hex)


def test_durable_cpu_process_roundtrip(runtime, admin, movie):
    owner = admin[0]["id"]
    source, _saved, job = setup(runtime, owner, movie)
    assert source["content_verified"] and job["status"] == "draft"
    assert runtime.get(owner, job["id"])["runs"] == []
    admitted = admit(runtime, owner, job["id"])
    assert admitted["status"] == "waiting"
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    assert len(done["runs"]) == 2
    assert all(run["status"] == "completed" for run in done["runs"])
    assert all(run["result"]["transport"] == "subprocess" for run in done["runs"])
    assert len(runtime.jobs(owner)) == 1
    assert runtime.run_local(owner, job["id"])["revision"] == done["revision"]
    for run in done["runs"]:
        for reference in run["result"]["outputs"].values():
            assert (
                runtime.store.path(owner, reference).stat().st_size
                == reference["bytes"]
            )
    # Reopen from a new repository object; no reliance on an in-memory runner.
    reopened = Execution(runtime.database, runtime.store).get(owner, job["id"])
    assert reopened["snapshot_sha256"] == done["snapshot_sha256"]
    assert reopened["runs"] == done["runs"]


def test_upload_resume_integrity_and_owner(runtime, admin, movie):
    owner = admin[0]["id"]
    request_id = uuid4().hex
    upload = runtime.upload_create(owner, "synthetic.mp4", len(movie), request_id)
    assert (
        runtime.upload_create(owner, "synthetic.mp4", len(movie), request_id)[
            "upload_id"
        ]
        == upload["upload_id"]
    )
    identity = upload["upload_id"]
    cut = len(movie) // 2
    first = runtime.upload_chunk(owner, identity, 0, movie[:cut])
    assert first["uploaded_bytes"] == cut
    assert (
        runtime.upload_chunk(owner, identity, 0, movie[:cut])["uploaded_bytes"] == cut
    )
    with pytest.raises(Conflict):
        runtime.upload_chunk(owner, identity, 0, b"incorrect")
    runtime.upload_verify(
        owner, identity, 0, cut, hashlib.sha256(movie[:cut]).hexdigest()
    )
    with pytest.raises(ValueError):
        runtime.upload_verify(owner, identity, 0, cut, "0" * 64)
    runtime.upload_chunk(owner, identity, cut, movie[cut:])
    completed = runtime.upload_complete(owner, identity)
    assert runtime.upload_complete(owner, identity)["asset_id"] == completed["asset_id"]
    with pytest.raises(Missing):
        runtime.upload_get(uuid4().hex, identity)
    assert (
        runtime.asset(owner, completed["asset_id"])["sha256"]
        == hashlib.sha256(movie).hexdigest()
    )


def test_definition_cas_history_restore_and_frozen_snapshot(runtime, admin, movie):
    owner = admin[0]["id"]
    _, saved, job = setup(runtime, owner, movie)
    update = {
        k: saved[k]
        for k in ("catalog_version", "revision", "name", "inputs", "nodes", "edges")
    }
    update["name"] = "수정한 정의"
    assert runtime.save_definition(owner, saved["id"], update)["revision"] == 2
    with pytest.raises(Conflict):
        runtime.save_definition(owner, saved["id"], update)
    assert runtime.get(owner, job["id"])["snapshot"]["definition"]["name"] == "CPU 검증"
    restored = runtime.restore_definition(owner, saved["id"], 2, 1)
    assert restored["revision"] == 3 and restored["name"] == "CPU 검증"
    assert [v["revision"] for v in runtime.versions(owner, saved["id"])] == [1, 2, 3]


def test_admission_concurrency_idempotency_expiry_and_no_unapproved_execution(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie)
    assert runtime.run_local(owner, job["id"])["status"] == "draft"
    consent = runtime.confirm(
        owner, job["id"], runtime.plan(owner, job["id"])["token"], uuid4().hex
    )
    request_id = uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: runtime.admit(owner, job["id"], consent["id"], request_id),
                range(2),
            )
        )
    assert results[0]["id"] == results[1]["id"]
    with runtime.database.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM execution_claims WHERE job_id=%s", (job["id"],)
            ).fetchone()["n"]
            == 1
        )
    with pytest.raises(Conflict):
        runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
    _, _, other = setup(runtime, owner, movie)
    expired = runtime.confirm(
        owner, other["id"], runtime.plan(owner, other["id"])["token"], uuid4().hex
    )
    with runtime.database.connection() as conn:
        conn.execute(
            "UPDATE execution_consents SET expires_at=now()-interval '1 second' WHERE id=%s",
            (expired["id"],),
        )
    with pytest.raises(Conflict):
        runtime.admit(owner, other["id"], expired["id"], uuid4().hex)


def test_review_save_confirm_new_admission_and_cancel_fencing(runtime, admin, movie):
    owner = admin[0]["id"]
    _, _, job = setup(
        runtime, owner, movie, graph("review", "encode", "validate_video")
    )
    admit(runtime, owner, job["id"])
    paused = runtime.run_local(owner, job["id"])
    assert paused["status"] == "review_required"
    review = paused["reviews"][0]
    saved = runtime.review_save(
        owner, review["id"], review["revision"], {"approved": True}
    )
    with pytest.raises(Conflict):
        runtime.review_confirm(owner, review["id"], review["revision"])
    runtime.review_confirm(owner, review["id"], saved["revision"])
    assert runtime.run_local(owner, job["id"])["status"] == "review_required"
    admit(runtime, owner, job["id"])
    assert runtime.run_local(owner, job["id"])["status"] == "completed"
    _, _, cancelled = setup(runtime, owner, movie)
    admit(runtime, owner, cancelled["id"])
    command = runtime.claim_next(owner, cancelled["id"])
    response = runtime.execute_command(owner, command)
    runtime.cancel(
        owner, cancelled["id"], runtime.get(owner, cancelled["id"])["revision"]
    )
    assert runtime.accept(owner, command, response)["status"] == "cancelled"
    assert runtime.get(owner, cancelled["id"])["runs"][0]["status"] == "quarantined"


def test_corrupt_source_and_model_nodes_fail_closed(runtime, admin, movie):
    owner = admin[0]["id"]
    source, _, job = setup(runtime, owner, movie)
    path = runtime.asset_path(owner, source["asset_id"])
    path.chmod(0o600)
    path.write_bytes(b"x" * source["size_bytes"])
    with pytest.raises(ValueError):
        runtime.plan(owner, job["id"])
    assert runtime.get(owner, job["id"])["status"] == "draft"


def test_content_symlink_traversal_and_hash_guard(tmp_path):
    store = ContentStore(tmp_path)
    owner = uuid4().hex
    reference = store.put(owner, [b"content"], "transcript")
    assert store.read(owner, reference) == b"content"
    with pytest.raises(ValueError):
        store.path(owner, {**reference, "storage_key": "../escape"})
    path = store.path(owner, reference)
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        store.path(owner, reference)


def test_runtime_api_auth_csrf_real_chunks_and_no_implicit_execution(
    runtime, admin, movie
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(
            runtime.database,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            content_store=runtime.store,
            local_execution=True,
        )
    )
    assert client.get("/api/videos").status_code == 401
    login(client, admin)
    assert client.get("/api/capabilities").json()["execution_enabled"] is True
    created = client.post(
        "/api/video-uploads",
        json={
            "filename": "actual-synthetic.mp4",
            "size": len(movie),
            "request_id": uuid4().hex,
        },
    )
    assert created.status_code == 201
    uid = created.json()["upload_id"]
    assert (
        client.put(
            "/api/video-uploads/" + uid + "/chunks?offset=0",
            content=movie,
            headers={"Content-Type": "application/octet-stream", "X-CSRF-Token": ""},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/video-uploads/" + uid + "/chunks?offset=0",
            content=movie,
            headers={"Content-Type": "application/octet-stream"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/video-uploads/" + uid + "/chunks?offset=0",
            content=b"x" * (4194304 + 1),
            headers={"Content-Type": "application/octet-stream"},
        ).status_code
        == 413
    )
    complete = client.post("/api/video-uploads/" + uid + "/complete", json={})
    assert complete.status_code == 200
    aid = complete.json()["asset_id"]
    assert (
        client.get(
            "/api/videos/" + aid + "/stream", headers={"Range": "bytes=0-31"}
        ).status_code
        == 206
    )
    assert (
        client.get("/api/videos/" + aid + "/thumbnail").headers["content-type"]
        == "image/jpeg"
    )
    wid = uuid4().hex
    saved = client.put(
        "/api/settings/workflow-definitions/" + wid,
        json=graph("encode", "validate_video"),
    )
    assert saved.status_code == 200
    selection = {
        "asset_id": aid,
        "definition_id": wid,
        "definition_revision": 1,
        "recovery_enabled": False,
        "options": {},
    }
    preview = client.post("/api/settings/work-entry/preview", json=selection)
    assert preview.status_code == 200
    created = client.post(
        "/api/settings/work-entry/create",
        json={
            **selection,
            "token": preview.json()["token"],
            "request_id": uuid4().hex,
            "paid_confirmed": False,
        },
    )
    assert created.status_code == 201
    identity = created.json()["id"]
    base = "/api/renewal/jobs/" + identity
    assert client.post(base + "/run", json={}).json()["status"] == "draft"
    plan = client.get(base + "/plan").json()
    consent = client.post(
        base + "/confirm", json={"token": plan["token"], "request_id": uuid4().hex}
    ).json()
    assert client.get(base).json()["runs"] == []
    admitted = client.post(
        base + "/admit", json={"consent_id": consent["id"], "request_id": uuid4().hex}
    )
    assert admitted.status_code == 200
    result = client.post(base + "/run", json={})
    assert result.status_code == 200 and result.json()["status"] == "completed"
    encoded = next(r for r in result.json()["runs"] if r["node_type"] == "encode")
    output = client.get(base + "/artifacts/" + encoded["id"] + "/video")
    assert (
        hashlib.sha256(output.content).hexdigest()
        == encoded["result"]["outputs"]["video"]["sha256"]
    )
    assert client.get("/api/jobs").json()["jobs"][0]["status"] == "COMPLETED"
    assert client.request("DELETE", "/api/videos/" + aid, json={}).status_code in (
        404,
        405,
    )


def test_recovery_reuses_only_verified_receipts_in_new_unadmitted_child(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie)
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, command)
    runtime.accept(owner, command, result)
    runtime.cancel(owner, job["id"], runtime.get(owner, job["id"])["revision"])
    nonce = uuid4().hex
    child = runtime.recover(owner, job["id"], nonce, acknowledge_duplicate_risk=True)
    assert child["status"] == "draft" and child["parent_id"] == job["id"]
    assert (
        len(child["runs"]) == 1
        and child["runs"][0]["result"]["reused_from"]["job_id"] == job["id"]
    )
    assert (
        runtime.recover(owner, job["id"], nonce, acknowledge_duplicate_risk=True)["id"]
        == child["id"]
    )
    assert runtime.run_local(owner, child["id"])["status"] == "draft"
    admit(runtime, owner, child["id"])
    assert runtime.run_local(owner, child["id"])["status"] == "completed"
    assert runtime.get(owner, job["id"])["status"] == "cancelled"


def test_duplicate_and_expired_result_never_advances(runtime, admin, movie):
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie)
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, command)
    accepted = runtime.accept(owner, command, result)
    assert runtime.accept(owner, command, result)["revision"] == accepted["revision"]
    with pytest.raises(Conflict):
        runtime.accept(owner, command, {**result, "status": "failed"})
    next_command = runtime.claim_next(owner, job["id"])
    assert next_command
    next_result = runtime.execute_command(owner, next_command)
    with runtime.database.connection() as conn:
        conn.execute(
            "UPDATE node_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (next_command["attempt_id"],),
        )
    state = runtime.accept(owner, next_command, next_result)
    assert state["status"] == "failed" and any(
        r["status"] == "quarantined" for r in state["runs"]
    )
    assert runtime.run_local(owner, job["id"])["status"] == "failed"


def test_production_cpu_browser_and_explicit_launcher(
    db, tmp_path, movie, object_settings=None
):
    if os.environ.get("MIDEAGENT_EXECUTION_BROWSER") != "1":
        pytest.skip("Explicit production bundle/browser opt-in required")
    import socket
    import time

    import httpx
    from test_execution import graph

    root = Path(__file__).resolve().parents[2]
    assert (root / "apps/web/dist/index.html").is_file()
    source = tmp_path / "browser-synthetic.mp4"
    source.write_bytes(movie)
    definition = tmp_path / "definition.json"
    definition.write_text(json.dumps(graph("review", "encode", "validate_video")))
    content = tmp_path / "content"
    content.mkdir(mode=0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = "http://127.0.0.1:" + str(port)
    evidence = os.environ.get("MIDEAGENT_EXECUTION_EVIDENCE")
    assert evidence and Path(evidence).is_absolute()
    env = {
        **os.environ,
        "MIDEAGENT_SYNTHETIC_DSN": db.dsn,
        "MIDEAGENT_TEST_ORIGIN": origin,
        "MIDEAGENT_TEST_MOVIE": str(source),
        "MIDEAGENT_TEST_DEFINITION": str(definition),
    }
    storage_args = ["--content-root", str(content)]
    if object_settings is not None:
        config, object_env = object_settings
        env.update(object_env)
        env["SYNTHETIC_APP_CONFIG"] = json.dumps(config)
        env["MIDEAGENT_EXPECT_TRANSPORT"] = "s3_subprocess"
        storage_args = [
            "--object-config-env",
            "SYNTHETIC_APP_CONFIG",
            "--agent-config-env",
            "SYNTHETIC_AGENT_CONFIG",
        ]
    server = subprocess.Popen(
        [
            __import__("sys").executable,
            "-m",
            "app.renewal_server",
            "--dsn-env",
            "MIDEAGENT_SYNTHETIC_DSN",
            *storage_args,
            "--origin",
            origin,
            "--allow-cpu",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 15
        ready = False
        with httpx.Client(trust_env=False) as client:
            while server.poll() is None and time.monotonic() < deadline:
                try:
                    ready = client.get(origin + "/api/auth/session").status_code == 200
                    if ready:
                        break
                except httpx.TransportError:
                    time.sleep(0.1)
        assert ready, "Explicit loopback launcher did not become ready"
        browser = subprocess.run(
            ["node", str(root / "tests/renewal/frontend-execution.mjs")],
            env=env,
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        Path(evidence).mkdir(parents=True, exist_ok=True)
        (Path(evidence) / "browser-raw.log").write_text(browser.stdout + browser.stderr)
        assert browser.returncode == 0, browser.stdout + browser.stderr
        print(browser.stdout)
    finally:
        server.terminate()
        try:
            server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)
        assert server.poll() is not None
