"""Saved real controlled-ASR failure -> explicit model-free artifact reprojection."""

import importlib
import importlib.util
import json

import pytest
from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie
from test_packed_projection_execution import projection_wire as _projection_wire
from test_packed_projection_execution import (
    test_formal_projection_is_explicit_and_trace_is_an_actual_cas_output as make_held_failure,
)
from video_service.content_store import ContentStore
from video_service.cpu_agents import digest
from video_service.postgres.execution import Execution

admin, db, movie, projection_wire = _admin, _db, _movie, _projection_wire
module = (
    importlib.import_module("video_service.postgres.projection_recovery")
    if importlib.util.find_spec("video_service.postgres.projection_recovery")
    else None
)


@pytest.fixture(params=[False, True])
def held(db, admin, movie, tmp_path, projection_wire, monkeypatch, request):
    from video_service import packed_projection

    original = packed_projection.project
    make_held_failure(
        db,
        admin,
        movie,
        tmp_path,
        projection_wire,
        "projection_failure",
        monkeypatch,
        long_profile=request.param,
    )
    monkeypatch.setattr(packed_projection, "project", original)
    owner = admin[0]["id"]
    with db.connection() as connection:
        job = connection.execute(
            "SELECT id FROM jobs WHERE owner_id=%s", (owner,)
        ).fetchone()["id"]
        run = connection.execute(
            "SELECT id FROM node_runs WHERE owner_id=%s AND job_id=%s AND node_type='transcribe'",
            (owner, job),
        ).fetchone()["id"]
    runtime = Execution(
        db, ContentStore(tmp_path)
    )  # No model runtimes/credentials/transports at all.
    return runtime, owner, job, run, projection_wire[1]


def preserved(runtime, owner, job):
    with runtime.database.connection() as connection:
        rows = {
            table: connection.execute(
                "SELECT to_jsonb(t) AS row FROM "
                + table
                + " t WHERE owner_id=%s AND "
                + ("id" if table == "jobs" else "job_id")
                + "=%s ORDER BY to_jsonb(t)::text",
                (owner, job),
            ).fetchall()
            for table in [
                "jobs",
                "node_runs",
                "agent_deliveries",
                "model_call_budgets",
                "model_chunk_attempts",
            ]
        }
    return digest(json.loads(json.dumps(rows, default=str)))


def test_preview_confirm_reprojects_without_model_or_source_job_mutation(held):
    runtime, owner, job, run, calls = held
    assert callable(getattr(module, "ProjectionRecovery", None))
    service = module.ProjectionRecovery(runtime)
    before = preserved(runtime, owner, job)
    prior_calls = list(calls)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    preview = service.preview(owner, job, run, policy=policy)
    assert (
        preview["status"] == "prepared"
        and preview["binding"]["packed_transcript"]["sha256"]
    )
    assert preserved(runtime, owner, job) == before and calls == prior_calls
    result = service.confirm(
        owner,
        job,
        preview["id"],
        context_sha256=preview["context_sha256"],
        acknowledge=True,
    )
    assert result["status"] == "completed"
    rows = json.loads(
        runtime.store.read(
            owner, result["outputs"]["transcript"], limit=16 * 1024 * 1024
        )
    )
    assert len(rows) == 2 and rows[0]["text"] == rows[1]["text"] == "Whole sentence"
    assert preserved(runtime, owner, job) == before and calls == prior_calls
    assert (
        service.confirm(
            owner,
            job,
            preview["id"],
            context_sha256=preview["context_sha256"],
            acknowledge=True,
        )
        == result
    )


def test_product_api_auth_csrf_shared_reads_and_original_failure_are_preserved(
    held, admin, db
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    runtime, owner, job, run, calls = held
    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
    )
    base = "/api/renewal/jobs/" + job + "/projection-recoveries"
    before = preserved(runtime, owner, job)
    prior = list(calls)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(base).status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
            headers={"Origin": "https://testserver"},
        )
        assert login.status_code == 200
        listing = client.get(base)
        assert listing.status_code == 200, listing.text
        candidate = listing.json()["candidates"][0]
        body = {"source_run_id": run, "policy": candidate["binding"]["policy"]}
        assert (
            client.post(
                base + "/preview", json=body, headers={"Origin": "https://testserver"}
            ).status_code
            == 403
        )
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        preview = client.post(base + "/preview", json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        row = preview.json()
        done = client.post(
            base + "/" + row["id"] + "/confirm",
            json={"context_sha256": row["context_sha256"], "acknowledge": True},
            headers=headers,
        )
        assert done.status_code == 200 and done.json()["status"] == "completed", (
            done.text
        )
        import hashlib

        for part, ref in done.json()["outputs"].items():
            response = client.get(base + "/" + row["id"] + "/files/" + part)
            assert (
                response.status_code == 200
                and hashlib.sha256(response.content).hexdigest() == ref["sha256"]
            )
        assert client.get("/api/renewal/jobs/" + job).json()["status"] == "failed"
    assert preserved(runtime, owner, job) == before and calls == prior


def test_preview_binds_the_accepted_result_receipt(held):
    runtime, owner, job, run, _ = held
    service = module.ProjectionRecovery(runtime)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    preview = service.preview(owner, job, run, policy=policy)
    with runtime.database.connection() as db:
        sha = db.execute(
            "SELECT payload_sha256 FROM message_inbox WHERE consumer=%s AND message_id=%s",
            ("result:" + owner, run),
        ).fetchone()["payload_sha256"]
    assert preview["binding"]["accepted_result_sha256"] == sha


def test_changed_context_or_policy_cannot_confirm_and_files_are_sha_verified(held):
    from video_service.postgres import Conflict

    runtime, owner, job, run, calls = held
    service = module.ProjectionRecovery(runtime)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    other = (
        "packed_projection_v5"
        if policy == "packed_projection_v2"
        else "packed_projection_v2"
    )
    with pytest.raises(Conflict):
        service.preview(owner, job, run, policy=other)
    preview = service.preview(owner, job, run, policy=policy)
    before = preserved(runtime, owner, job)
    prior = list(calls)
    with pytest.raises(Conflict):
        service.confirm(
            owner, job, preview["id"], context_sha256="0" * 64, acknowledge=True
        )
    with pytest.raises(Conflict):
        service.confirm(
            owner,
            job,
            preview["id"],
            context_sha256=preview["context_sha256"],
            acknowledge=False,
        )
    path = runtime.store.path(owner, preview["binding"]["packed_transcript"])
    raw = path.read_bytes()
    mode = path.stat().st_mode
    stamp = path.stat().st_mtime_ns
    path.chmod(0o600)
    path.write_bytes(
        raw.replace(b"Whole", b"Wrong", 1)
    )  # Disposable synthetic CAS only, same length.
    import os

    os.utime(path, ns=(stamp, stamp))
    with pytest.raises(ValueError):
        service.confirm(
            owner,
            job,
            preview["id"],
            context_sha256=preview["context_sha256"],
            acknowledge=True,
        )
    path.write_bytes(raw)
    path.chmod(mode)
    assert service.list(owner, job)["operations"][0]["status"] == "prepared"
    assert preserved(runtime, owner, job) == before and calls == prior


def test_lost_final_commit_is_held_and_confirm_never_replays_cas_or_models(
    held, monkeypatch
):
    import psycopg

    runtime, owner, job, run, calls = held
    service = module.ProjectionRecovery(runtime)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    preview = service.preview(owner, job, run, policy=policy)
    before = preserved(runtime, owner, job)
    prior = list(calls)
    with runtime.database.connection() as db:
        db.execute(
            "CREATE FUNCTION reject_reprojection_final() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status='completed' THEN RAISE EXCEPTION 'controlled_final_commit_failure'; END IF; RETURN NEW; END $$"
        )
        db.execute(
            "CREATE CONSTRAINT TRIGGER reject_reprojection_final AFTER UPDATE ON projection_recoveries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_reprojection_final()"
        )
    with pytest.raises(psycopg.Error):
        service.confirm(
            owner,
            job,
            preview["id"],
            context_sha256=preview["context_sha256"],
            acknowledge=True,
        )
    assert service.list(owner, job)["operations"][0]["status"] == "running"

    def forbidden(*args, **kwargs):
        raise AssertionError("Uncertain projection must not be replayed")

    monkeypatch.setattr(runtime.store, "put", forbidden)
    row = service.confirm(
        owner,
        job,
        preview["id"],
        context_sha256=preview["context_sha256"],
        acknowledge=True,
    )
    assert (
        row["status"] == "running"
        and preserved(runtime, owner, job) == before
        and calls == prior
    )


def test_shared_reader_can_read_recovered_files_but_cannot_create_or_confirm(
    held, admin, db
):
    import secrets

    from app.renewal import create_app
    from fastapi.testclient import TestClient
    from video_service.postgres.accounts import Accounts

    runtime, owner, job, run, calls = held
    service = module.ProjectionRecovery(runtime)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    preview = service.preview(owner, job, run, policy=policy)
    done = service.confirm(
        owner,
        job,
        preview["id"],
        context_sha256=preview["context_sha256"],
        acknowledge=True,
    )
    password = secrets.token_urlsafe(24)
    member = Accounts(db).create("reprojection-reader", password, actor_id=owner)
    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
    )
    base = "/api/renewal/jobs/" + job + "/projection-recoveries"
    before = preserved(runtime, owner, job)
    prior = list(calls)
    with TestClient(app, base_url="https://testserver") as client:
        signed = client.post(
            "/api/auth/login",
            json={"username": member["username"], "password": password},
            headers={"Origin": "https://testserver"},
        )
        assert signed.status_code == 200
        listing = client.get(base)
        assert listing.status_code == 200 and listing.json()["can_manage"] is False
        assert (
            client.get(base + "/" + done["id"] + "/files/transcript").status_code == 200
        )
        assert (
            client.get(base + "/sources/" + run + "/packed_transcript").status_code
            == 200
        )
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": signed.json()["csrf_token"],
        }
        assert (
            client.post(
                base + "/preview",
                json={"source_run_id": run, "policy": policy},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                base + "/" + preview["id"] + "/confirm",
                json={"context_sha256": preview["context_sha256"], "acknowledge": True},
                headers=headers,
            ).status_code
            == 403
        )
    assert preserved(runtime, owner, job) == before and calls == prior


def test_mismatched_accepted_commit_receipt_is_blocked_without_model_recall(held):
    from video_service.postgres import Conflict

    runtime, owner, job, run, calls = held
    service = module.ProjectionRecovery(runtime)
    policy = service.list(owner, job)["candidates"][0]["binding"]["policy"]
    # Deliberately corrupt only this disposable fixture's acceptance evidence.
    with runtime.database.connection() as db:
        db.execute(
            "UPDATE message_inbox SET payload_sha256=%s WHERE consumer=%s AND message_id=%s",
            ("0" * 64, "result:" + owner, run),
        )
    before = preserved(runtime, owner, job)
    prior = list(calls)
    assert service.list(owner, job)["candidates"][0]["eligible"] is False
    with pytest.raises(Conflict):
        service.preview(owner, job, run, policy=policy)
    assert service.list(owner, job)["operations"] == []
    assert preserved(runtime, owner, job) == before and calls == prior


def test_preview_file_verification_does_not_hold_source_job_lock_or_api_event_loop(
    held, admin, db, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.renewal import create_app
    from fastapi.testclient import TestClient

    runtime, owner, job, run, _ = held
    service = module.ProjectionRecovery(runtime)
    binding = service.list(owner, job)["candidates"][0]["binding"]
    entered = threading.Event()
    release = threading.Event()
    original = runtime.store.path

    def blocked(owned, ref):
        if ref["sha256"] == binding["audio"]["sha256"]:
            entered.set()
            assert release.wait(10)
        return original(owned, ref)

    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app, base_url="https://testserver") as client:
        signed = client.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
            headers={"Origin": "https://testserver"},
        )
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": signed.json()["csrf_token"],
        }
        monkeypatch.setattr(runtime.store, "path", blocked)
        with ThreadPoolExecutor(max_workers=2) as pool:
            preview = pool.submit(
                client.post,
                "/api/renewal/jobs/" + job + "/projection-recoveries/preview",
                json={"source_run_id": run, "policy": binding["policy"]},
                headers=headers,
            )
            try:
                assert entered.wait(5)
                status = pool.submit(client.get, "/api/renewal/jobs/" + job).result(
                    timeout=2
                )
                assert status.status_code == 200 and status.json()["status"] == "failed"
            finally:
                release.set()
            assert preview.result(timeout=8).status_code == 200
