"""Durable full-video preview requests; isolated DB, no operating media."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_execution import movie as movie  # noqa: PLC0414 - pytest fixture export
from test_foundation import admin as admin  # noqa: PLC0414 - pytest fixture export
from test_foundation import db as db  # noqa: PLC0414 - pytest fixture export
from test_foundation import login
from video_service.content_store import ContentStore
from video_service.cpu_agents import probe
from app.renewal import create_app


@pytest.fixture
def preview_source(db, admin, movie, tmp_path):
    store = ContentStore(tmp_path)
    owner = admin[0]["id"]
    reference = store.put(owner, [movie], "video")
    identity = uuid4().hex
    metadata = {
        "registration_state": "verified",
        "media": probe(store.path(owner, reference)),
    }
    with db.connection() as connection:
        connection.execute(
            "INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                owner,
                identity,
                "preview-source.mp4",
                "sha256:" + reference["sha256"],
                reference["bytes"],
                reference["sha256"],
                Jsonb(metadata),
            ),
        )
    return store, identity


def test_request_returns_queued_without_media_io_and_dedupes_after_api_restart(
    db, admin, preview_source, monkeypatch
):
    store, identity = preview_source

    def forbidden(*_):
        raise AssertionError("HTTP request must never materialize or transcode media")

    monkeypatch.setattr(store, "path", forbidden)
    clients = []
    try:
        ids = []
        for _ in range(2):
            client = TestClient(
                create_app(
                    db,
                    content_store=store,
                    allowed_origins=("http://testserver",),
                    secure_cookies=False,
                ),
                base_url="http://testserver",
            )
            clients.append(client)
            login(client, admin)
            response = client.post("/api/videos/" + identity + "/preview/full", json={})
            assert response.status_code == 202, response.text
            value = response.json()
            assert value["state"] == "queued" and value["coverage"] == "full"
            ids.append(value["id"])
        assert ids[0] == ids[1]
        with db.connection() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) AS n FROM video_preview_jobs"
                ).fetchone()["n"]
                == 1
            )
    finally:
        for client in clients:
            client.close()


def test_exclusive_worker_keeps_pending_and_holds_interrupted_attempt(
    db, preview_source, admin, tmp_path
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    from video_service.postgres import Conflict

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    pending = service.request_asset(admin[0]["id"], identity)
    with PreviewWorker(service, tmp_path).exclusive():
        with pytest.raises(Conflict):
            with PreviewWorker(service, tmp_path).exclusive():
                pass
    # A normal idle stop did not claim or lose the queued job.
    with PreviewWorker(service, tmp_path).exclusive() as runner:
        row = runner.claim_next()
        assert row["id"] == pending["id"] and row["claim_count"] == 1
        assert row["stage"] == "loading"
    # Losing the process/session mid-attempt must not replay the work.
    with PreviewWorker(service, tmp_path).exclusive() as replacement:
        assert replacement.claim_next() is None
    with db.connection() as connection:
        row = connection.execute(
            "SELECT state,claim_count FROM video_preview_jobs WHERE id=%s",
            (pending["id"],),
        ).fetchone()
        assert row == {"state": "held", "claim_count": 1}


def test_independent_worker_verifies_full_file_before_ready(
    db, preview_source, admin, tmp_path
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    import hashlib

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        row = worker.claim_next()
        worker.process(row)
    state = service.get(admin[0]["id"], task["id"])
    assert state["state"] == "ready" and state["coverage"] == "full"
    assert abs(state["media"]["duration"] - 0.6) < 0.1
    path = service.file(admin[0]["id"], task["id"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == state["sha256"]


def test_cancelled_ready_preview_is_not_downloadable_and_source_is_unchanged(
    db, preview_source, admin, tmp_path
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    from video_service.postgres import Missing

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    with db.connection() as connection:
        original = connection.execute(
            "SELECT * FROM assets WHERE id=%s", (identity,)
        ).fetchone()
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
    service.cancel(admin[0]["id"], task["id"])
    assert service.get(admin[0]["id"], task["id"])["state"] == "cancelled"
    with pytest.raises(Missing):
        service.file(admin[0]["id"], task["id"])
    with db.connection() as connection:
        assert (
            connection.execute(
                "SELECT * FROM assets WHERE id=%s", (identity,)
            ).fetchone()
            == original
        )


def test_acceptance_queues_sidecar_without_sync_webm_or_receipt_rewrite(
    db, admin, movie, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    from test_execution import graph, admit
    import video_service.web_preview as legacy

    def forbidden(*_):
        raise AssertionError("WebM transcoding must not run in upload/adoption")

    monkeypatch.setattr(legacy, "create_preview", forbidden)
    runtime = Execution(db, ContentStore(tmp_path))
    source = runtime.ingest(admin[0]["id"], "sidecar-source.mp4", movie)
    definition = uuid4().hex
    runtime.save_definition(admin[0]["id"], definition, graph("encode"))
    job = runtime.create(
        admin[0]["id"], source["asset_id"], definition, 1, request_id=uuid4().hex
    )
    admit(runtime, admin[0]["id"], job["id"])
    command = runtime.claim_next(admin[0]["id"], job["id"])
    runtime.accept(
        admin[0]["id"], command, runtime.execute_command(admin[0]["id"], command)
    )
    with db.connection() as connection:
        run = connection.execute(
            "SELECT * FROM node_runs WHERE id=%s", (command["attempt_id"],)
        ).fetchone()
        assert run["status"] == "completed"
        tasks = connection.execute(
            "SELECT subject,state FROM video_preview_jobs"
        ).fetchall()
        assert len(tasks) == 2 and {x["subject"]["kind"] for x in tasks} == {
            "asset",
            "artifact",
        }
        assert all(x["state"] == "queued" for x in tasks)
        assert run["result"]["previews"] == {}
    from video_service.postgres.video_previews import VideoPreviews

    with db.connection() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        bound = VideoPreviews(runtime).artifact_source(
            connection, job["id"], command["attempt_id"], "video"
        )
        assert bound[0]["attempt_id"] == command["attempt_id"]
    from video_service.full_preview_worker import PreviewWorker

    service = VideoPreviews(runtime)
    manifest = run["result"]["ticket_artifacts"]["manifest"]["reference"]
    manifest_bytes = runtime.store.path(admin[0]["id"], manifest).read_bytes()
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
        worker.process(worker.claim_next())
    with db.connection() as connection:
        assert (
            connection.execute(
                "SELECT * FROM node_runs WHERE id=%s", (run["id"],)
            ).fetchone()
            == run
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM video_preview_jobs WHERE state='ready'"
            ).fetchone()["n"]
            == 2
        )
    assert runtime.store.path(admin[0]["id"], manifest).read_bytes() == manifest_bytes


def test_unsupported_preview_does_not_reject_normal_upload(
    db, admin, movie, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    import video_service.postgres.intake as intake_module

    actual = intake_module.probe
    monkeypatch.setattr(
        intake_module, "probe", lambda path: {**actual(path), "duration": 21601.0}
    )
    runtime = Execution(db, ContentStore(tmp_path))
    asset = runtime.ingest(admin[0]["id"], "long-preview-unsupported.mp4", movie)
    assert asset["asset_id"]
    with db.connection() as connection:
        row = connection.execute(
            "SELECT state,error_code FROM video_preview_jobs"
        ).fetchone()
        assert row == {"state": "failed", "error_code": "preview_input_budget"}


def test_worker_entrypoint_is_explicitly_opt_in():
    import subprocess

    result = subprocess.run(
        ["python", "-m", "video_service.full_preview_worker", "--help"],
        capture_output=True,
        check=True,
        text=True,
    )
    assert "--enable-full-previews" in result.stdout
    assert "--dsn-file" in result.stdout


def test_wall_budget_interrupts_storage_io_without_ready(
    db, admin, preview_source, tmp_path, monkeypatch
):
    import time
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews, FULL_PROFILE
    from video_service.full_preview_worker import PreviewWorker

    store, identity = preview_source
    monkeypatch.setitem(FULL_PROFILE, "wall_seconds", 0.2)
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    actual = store.path
    progress = []

    def delayed(*args):
        time.sleep(0.6)
        progress.append("I/O completed after deadline")
        return actual(*args)

    monkeypatch.setattr(store, "path", delayed)
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
    assert service.get(admin[0]["id"], task["id"])["state"] == "failed"
    assert progress == []
    assert list(tmp_path.glob("full-preview-*")) == []


def test_download_rechecks_cancellation_after_storage_read(
    db, admin, preview_source, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    from video_service.postgres import Missing

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
    actual = store.path

    def cancel_during_read(*args):
        result = actual(*args)
        service.cancel(admin[0]["id"], task["id"])
        return result

    monkeypatch.setattr(store, "path", cancel_during_read)
    with pytest.raises(Missing):
        service.file(admin[0]["id"], task["id"])


def test_truncated_generation_never_becomes_ready(
    db, admin, preview_source, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    import video_service.cpu_agents as native

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    original = native.ffmpeg
    monkeypatch.setattr(native, "ffmpeg", lambda: [*original(), "-t", "0.2"])
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
    result = service.get(admin[0]["id"], task["id"])
    assert result["state"] == "failed" and result["download_url"] is None


def test_native_source_dimension_limit_is_independent(
    db, admin, preview_source, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    import video_service.cpu_agents as native

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)
    original = native.probe
    monkeypatch.setattr(
        native, "probe", lambda path: {**original(path), "width": 8192, "height": 8}
    )
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
    assert service.get(admin[0]["id"], task["id"])["state"] == "failed"


def test_full_preview_routes_keep_auth_and_csrf(db, admin, preview_source):
    store, identity = preview_source
    with TestClient(
        create_app(
            db,
            content_store=store,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
        ),
        base_url="http://testserver",
    ) as client:
        url = "/api/videos/" + identity + "/preview/full"
        assert client.post(url, json={}).status_code == 401
        login(client, admin)
        client.headers.pop("X-CSRF-Token")
        assert client.post(url, json={}).status_code == 403
        with db.connection() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) AS n FROM video_preview_jobs"
                ).fetchone()["n"]
                == 0
            )


def test_unknown_storage_is_held_with_private_scope_and_no_reclaim(
    db, admin, preview_source, tmp_path, monkeypatch
):
    from video_service.postgres.execution import Execution
    from video_service.postgres.video_previews import VideoPreviews
    from video_service.full_preview_worker import PreviewWorker
    from video_service.object_store import ObjectStoreError

    store, identity = preview_source
    service = VideoPreviews(Execution(db, store))
    task = service.request_asset(admin[0]["id"], identity)

    def unknown(*_):
        raise ObjectStoreError("Object write failed; outcome may be unknown")

    monkeypatch.setattr(store, "path", unknown)
    with PreviewWorker(service, tmp_path).exclusive() as worker:
        worker.process(worker.claim_next())
        assert worker.claim_next() is None
    assert service.get(admin[0]["id"], task["id"])["state"] == "held"
    assert len(list(tmp_path.glob("full-preview-*"))) == 1
