"""S3 protocol tests use an ephemeral loopback emulator, not MinIO deployment.

Independent subprocesses have separate private roots and no DB credentials.
This proves wire/storage contracts, not MinIO vendor or multi-host acceptance.
"""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from test_execution import admit, graph, setup
from test_execution import movie as _movie_fixture
from test_foundation import admin as _admin_fixture
from test_foundation import db as _db_fixture
from test_foundation import login
from video_service.object_agent import ObjectAgentExecutor, execute
from video_service.object_store import AttemptUnknown, ObjectStoreError, from_config
from video_service.postgres import Conflict
from video_service.postgres.execution import Execution

# Register imported pytest fixtures without shadowing unused imports.
admin = _admin_fixture
db = _db_fixture
movie = _movie_fixture


@pytest.fixture
def objects(tmp_path):
    pytest.importorskip("moto.server")
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    try:
        host, port = server.get_host_and_port()
        assert host == "127.0.0.1"
        env = {
            **os.environ,
            "SYNTHETIC_S3_ACCESS": uuid4().hex,
            "SYNTHETIC_S3_SECRET": uuid4().hex,
        }
        config = {
            "endpoint": f"http://127.0.0.1:{port}",
            "bucket": "renewal-synthetic",
            "region": "us-east-1",
            "prefix": uuid4().hex,
            "cache_root": str(tmp_path / "app"),
            "access_key_env": "SYNTHETIC_S3_ACCESS",
            "secret_key_env": "SYNTHETIC_S3_SECRET",
        }
        Path(config["cache_root"]).mkdir(mode=0o700)
        store = from_config(config, environ=env)
        store.client.create_bucket(Bucket=config["bucket"])
        agent_config = {**config, "cache_root": str(tmp_path / "agent")}
        Path(agent_config["cache_root"]).mkdir(mode=0o700)
        env["SYNTHETIC_AGENT_CONFIG"] = json.dumps(agent_config)
        yield store, config, agent_config, env
    finally:
        server.stop()


def command(reference, kind="encode"):
    return {
        "protocol_version": 1,
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "generation": 1,
        "agent": {"id": kind, "revision": "1"},
        "inputs": {"video": reference},
        "options": {"subtitle_mode": "none"} if kind == "encode" else {},
    }


def test_s3_roundtrip_cross_cache_owner_integrity_and_no_overwrite(objects, tmp_path):
    store, config, _, env = objects
    owner = uuid4().hex
    ref = store.put(owner, [b"isolated content"], "transcript")
    remote = {**config, "cache_root": str(tmp_path / "other-host")}
    Path(remote["cache_root"]).mkdir(mode=0o700)
    other = from_config(remote, environ=env)
    assert not (other.owner_root(owner) / ref["storage_key"]).exists()
    assert other.read(owner, ref) == b"isolated content"
    assert store.put(owner, [b"isolated content"], "transcript") == ref
    with pytest.raises(ObjectStoreError):
        other.path(uuid4().hex, ref)
    with pytest.raises(ObjectStoreError):
        other.path(owner, {**ref, "storage_key": "../escape"})
    # Test-only corrupt remote bytes, then ensure neither cache nor same-name put hides it.
    store.client.put_object(
        Bucket=config["bucket"],
        Key=store._key(owner, ref["storage_key"]),
        Body=b"corrupt",
    )
    with pytest.raises(ObjectStoreError):
        other.path(owner, ref)
    with pytest.raises(ObjectStoreError):
        store.put(owner, [b"isolated content"], "transcript")


def test_db_free_object_agent_subprocess_and_cross_workspace_redelivery(
    objects, movie, tmp_path
):
    store, _config, agent_config, env = objects
    owner = uuid4().hex
    ref = store.put(owner, [movie], "video")
    cmd = command(ref)
    executor = ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=env)
    result = executor(owner, cmd)
    assert result["status"] == "completed" and result["transport"] == "s3_subprocess"
    assert store.path(owner, result["outputs"]["video"]).is_file()
    assert not (store.owner_root(owner) / "attempts").exists()
    fresh = tmp_path / "replay-host"
    fresh.mkdir(mode=0o700)
    replay_env = {
        **env,
        "SYNTHETIC_AGENT_CONFIG": json.dumps(
            {**agent_config, "cache_root": str(fresh)}
        ),
    }
    replay = ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=replay_env)(
        owner, cmd
    )
    assert replay == result
    assert not (fresh / owner / "attempts").exists(), (
        "Replay must not launch ffmpeg in a new workspace"
    )
    assert all(
        k not in executor.env
        for k in ("MIDEAGENT_TEST_DSN", "OPENAI_API_KEY", "GEMINI_API_KEY")
    )
    reserved = command(ref)
    assert store.claim_attempt(owner, reserved) is None
    with pytest.raises(AttemptUnknown):
        execute(store, owner, reserved, agent="encode")


def test_postgres_api_object_agent_review_cancel_recovery(objects, db, admin, movie):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    store, _, _, env = objects
    executor = ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=env)
    runtime = Execution(db, store, agent_executor=executor)
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
    runtime.review_confirm(owner, review["id"], saved["revision"])
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed"
    encoded = next(r for r in done["runs"] if r["node_type"] == "encode")
    assert encoded["result"]["transport"] == "s3_subprocess"
    client = TestClient(
        create_app(
            db,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            content_store=store,
            local_execution=True,
            agent_executor=executor,
        )
    )
    login(client, admin)
    uri = "/api/renewal/jobs/" + job["id"] + "/artifacts/" + encoded["id"] + "/video"
    response = client.get(uri)
    assert response.status_code == 200
    assert (
        hashlib.sha256(response.content).hexdigest()
        == encoded["result"]["outputs"]["video"]["sha256"]
    )
    ranged = client.get(uri, headers={"Range": "bytes=0-31"})
    assert ranged.status_code == 206 and ranged.content == response.content[:32]
    _, _, cancelled = setup(runtime, owner, movie)
    admit(runtime, owner, cancelled["id"])
    cmd = runtime.claim_next(owner, cancelled["id"])
    result = runtime.execute_command(owner, cmd)
    assert runtime.execute_command(owner, cmd) == result
    runtime.cancel(
        owner, cancelled["id"], runtime.get(owner, cancelled["id"])["revision"]
    )
    stale = runtime.accept(owner, cmd, result)
    assert (
        stale["status"] == "cancelled" and stale["runs"][0]["status"] == "quarantined"
    )
    child = runtime.recover(
        owner, cancelled["id"], uuid4().hex, acknowledge_duplicate_risk=True
    )
    assert child["status"] == "draft"
    admit(runtime, owner, child["id"])
    assert runtime.run_local(owner, child["id"])["status"] == "completed"


def test_transport_confirm_and_ack_after_persistence(objects, db, admin, movie):
    from video_service.durable_transport import DurableTransport

    store, _, _, env = objects
    runtime = Execution(
        db,
        store,
        agent_executor=ObjectAgentExecutor("SYNTHETIC_AGENT_CONFIG", environ=env),
    )
    transport = DurableTransport(runtime)
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie)
    admit(runtime, owner, job["id"])
    cmd = runtime.claim_next(owner, job["id"])
    with pytest.raises(Conflict):
        transport.publish_exact(
            owner, job["id"], cmd["attempt_id"], lambda *args: False
        )
    assert transport.publish_exact(
        owner, job["id"], cmd["attempt_id"], lambda *args: True
    )
    assert not transport.publish_exact(
        owner,
        job["id"],
        cmd["attempt_id"],
        lambda *args: pytest.fail("Duplicate publish"),
    )
    acks = []
    result = transport.consume_command(
        owner, cmd, lambda *args: True, lambda: acks.append("command")
    )

    def ack_result():
        with db.connection() as conn:
            row = conn.execute(
                "SELECT status FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, job["id"], cmd["attempt_id"]),
            ).fetchone()
        assert row["status"] == "completed"
        acks.append("result")

    transport.consume_result(owner, cmd, result, ack_result)
    assert acks == ["command", "result"]


def test_config_refuses_implicit_credentials_and_insecure_remote(objects):
    _, config, _, env = objects
    with pytest.raises(ObjectStoreError):
        from_config({**config, "endpoint": "http://object.example"}, environ=env)
    with pytest.raises(ObjectStoreError):
        from_config(config, environ={})
    with pytest.raises(ObjectStoreError):
        from_config({**config, "prefix": "../other"}, environ=env)


def test_production_object_storage_browser(objects, db, tmp_path, movie, monkeypatch):
    from test_execution import (
        test_production_cpu_browser_and_explicit_launcher as browser_case,
    )

    _, config, _, env = objects
    evidence = os.environ.get("MIDEAGENT_EXECUTION_EVIDENCE")
    if evidence:
        monkeypatch.setenv("MIDEAGENT_EXECUTION_EVIDENCE", evidence + "/object-storage")
        env["MIDEAGENT_EXECUTION_EVIDENCE"] = evidence + "/object-storage"
    browser_case(db, tmp_path, movie, object_settings=(config, env))
