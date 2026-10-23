"""Real disposable-PG guard-loss regressions. No media/provider/operating work."""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_foundation import admin as admin  # noqa: PLC0414 - pytest fixture export
from test_foundation import db as db  # noqa: PLC0414 - pytest fixture export
from video_service.full_preview_worker import PreviewWorker
from video_service.postgres import Conflict
from video_service.postgres.video_previews import FULL_PROFILE


def service(db, root):
    return SimpleNamespace(
        database=db,
        binding_matches=lambda *_: True,
        store=SimpleNamespace(path=lambda *_: root / "source.bin"),
    )


def queued(db, owner):
    with db.connection() as connection:
        return connection.execute(
            "INSERT INTO video_preview_jobs(id,request_key,requested_by,storage_owner_id,subject,source_ref,profile) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4().hex,
                uuid4().hex + uuid4().hex,
                owner,
                owner,
                Jsonb({}),
                Jsonb(
                    {
                        "storage_key": "blobs/" + "a" * 64,
                        "sha256": "a" * 64,
                        "bytes": 1,
                        "type": "video",
                    }
                ),
                Jsonb(FULL_PROFILE),
            ),
        ).fetchone()


def rows(db):
    with db.connection() as connection:
        return connection.execute(
            "SELECT * FROM video_preview_jobs ORDER BY id"
        ).fetchall()


def terminate(db, worker):
    pid = worker.guard.info.backend_pid
    with psycopg.connect(db.dsn, autocommit=True) as admin:
        assert admin.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0]


def test_live_stale_object_cannot_claim_after_replacement(db, admin, tmp_path):
    first = PreviewWorker(service(db, tmp_path), tmp_path)
    second = PreviewWorker(service(db, tmp_path), tmp_path)
    with first.exclusive():
        terminate(db, first)
        with second.exclusive():
            queued(db, admin[0]["id"])
            queued(db, admin[0]["id"])
            try:
                stale = first.claim_next()
            except (Conflict, psycopg.Error):
                stale = None
            assert stale is None, (
                "Old live object claimed after its PG guard session died"
            )
            assert second.claim_next() is not None
            assert second.claim_next() is None, (
                "A single owner may not accumulate running claims"
            )
            assert sorted(x["state"] for x in rows(db)) == ["queued", "running"]


def test_idle_restart_preserves_pending_and_interrupted_claim_is_held(
    db, admin, tmp_path
):
    value = queued(db, admin[0]["id"])
    before = rows(db)
    with PreviewWorker(service(db, tmp_path), tmp_path).exclusive():
        pass
    assert rows(db) == before
    with PreviewWorker(service(db, tmp_path), tmp_path).exclusive() as worker:
        assert worker.claim_next()["id"] == value["id"]
    with PreviewWorker(service(db, tmp_path), tmp_path).exclusive() as replacement:
        assert replacement.held and replacement.claim_next() is None
    final = rows(db)[0]
    assert final["state"] == "held" and final["claim_count"] == 1


def test_guard_loss_after_input_read_prevents_native_launch(
    db, admin, tmp_path, monkeypatch
):
    import subprocess
    import video_service.cpu_agents as native

    value = queued(db, admin[0]["id"])
    api = service(db, tmp_path)
    worker = PreviewWorker(api, tmp_path)
    monkeypatch.setattr(
        native, "probe", lambda *_: {"duration": 1.0, "width": 160, "height": 90}
    )
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: launched.append(True))
    with worker.exclusive():
        claim = worker.claim_next()
        before = rows(db)

        def lose_on_read(*_):
            terminate(db, worker)
            return tmp_path / "source.bin"

        api.store.path = lose_on_read
        with pytest.raises((Conflict, psycopg.Error)):
            worker.process(claim)
        assert launched == []
        assert rows(db) == before
    assert len(list(tmp_path.glob("full-preview-*"))) == 1
    assert rows(db)[0]["id"] == value["id"]


def test_lost_owner_cannot_commit_ready_or_overwrite_original_state(
    db, admin, tmp_path
):
    queued(db, admin[0]["id"])
    api = service(db, tmp_path)
    worker = PreviewWorker(api, tmp_path)
    with worker.exclusive():
        claim = worker.claim_next()
        before = rows(db)

        def lose_during_finalization(*_):
            terminate(db, worker)
            return True

        api.binding_matches = lose_during_finalization
        with pytest.raises((Conflict, psycopg.Error)):
            worker._finish(
                claim,
                "ready",
                {
                    "bytes": 1,
                    "type": "web_video",
                    "sha256": "b" * 64,
                    "storage_key": "blobs/" + "b" * 64,
                },
                {"duration": 1.0},
            )
        assert rows(db) == before
    assert rows(db)[0]["state"] == "running" and rows(db)[0]["output_ref"] is None


class DisconnectOnClaimUpdate:
    def __init__(self, connection, database, worker):
        self.connection, self.database, self.worker = connection, database, worker

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, query, *args, **kwargs):
        cursor = self.connection.execute(query, *args, **kwargs)
        if str(query).startswith("UPDATE video_preview_jobs SET state='running'"):
            terminate(self.database, self.worker)
        return cursor


def test_claim_lost_before_commit_returns_nothing_and_preserves_queued(
    db, admin, tmp_path
):
    queued(db, admin[0]["id"])
    before = rows(db)
    worker = PreviewWorker(service(db, tmp_path), tmp_path)
    with worker.exclusive():
        worker.guard = DisconnectOnClaimUpdate(worker.guard, db, worker)
        with pytest.raises((Conflict, psycopg.Error)):
            worker.claim_next()
        assert rows(db) == before
    with pytest.raises(Conflict, match="reconnect"):
        with worker.exclusive():
            pass


@pytest.mark.parametrize("phase", ["during_launch", "during_poll"])
def test_native_guard_loss_stops_owned_child_and_preserves_unknown_scope(
    db, admin, tmp_path, monkeypatch, phase
):
    import subprocess
    import sys
    import video_service.cpu_agents as native

    queued(db, admin[0]["id"])
    api = service(db, tmp_path)
    worker = PreviewWorker(api, tmp_path)
    monkeypatch.setattr(
        native, "probe", lambda *_: {"duration": 1.0, "width": 160, "height": 90}
    )
    actual_popen = subprocess.Popen
    children = []
    before_loss = []

    def lose():
        before_loss.extend(rows(db))
        terminate(db, worker)

    def spawn(*_args, **kwargs):
        # A real owned short-lived Python child, NOT ffmpeg or an inference job.
        child = actual_popen(
            [sys.executable, "-c", "import time;time.sleep(1)"], **kwargs
        )
        children.append(child)
        if phase == "during_launch":
            lose()
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    actual_current = worker._current

    def current(row):
        if children and not before_loss:
            lose()
        return actual_current(row)

    monkeypatch.setattr(worker, "_current", current)
    with worker.exclusive():
        claim = worker.claim_next()
        with pytest.raises((Conflict, psycopg.Error)):
            worker.process(claim)
        assert len(children) == 1 and children[0].poll() is not None
        assert worker.guard_lost and worker.held
        assert rows(db) == before_loss
    assert len(list(tmp_path.glob("full-preview-*"))) == 1
    with PreviewWorker(api, tmp_path).exclusive() as replacement:
        assert replacement.held and replacement.claim_next() is None
    final = rows(db)[0]
    assert (
        final["state"] == "held"
        and final["claim_count"] == 1
        and final["output_ref"] is None
    )
