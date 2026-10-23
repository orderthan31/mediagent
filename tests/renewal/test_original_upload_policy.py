"""Original-only upload policy. Disposable PG only; explicitly exclude020."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.renewal import create_app
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.content_store import MAX_CONTENT, ContentStore
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.intake import Intake


@pytest.fixture
def db():
    dsn = os.environ.get("MIDEAGENT_TEST_DSN")
    if not dsn or os.environ.get("MIDEAGENT_TEST_DISPOSABLE") != "1":
        pytest.skip("Explicit disposable PG required")
    schema = "original_upload_" + uuid4().hex
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    instance = Database(make_conninfo(dsn, options="-c search_path=" + schema))
    import video_service.postgres as pg

    with instance.connection() as c:
        c.execute(
            "CREATE TABLE schema_migrations(name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted((Path(pg.__file__).parent / "migrations").glob("*.sql")):
            if path.name.startswith("020_"):
                continue
            raw = path.read_bytes()
            c.execute(raw.decode())
            c.execute(
                "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
                (path.name, hashlib.sha256(raw).hexdigest()),
            )
    try:
        yield instance
    finally:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def original(db, tmp_path):
    root = tmp_path / "content"
    root.mkdir()
    runtime = Intake(db, ContentStore(root))
    user = Accounts(db).create(
        "isolated-original-admin", "synthetic-fixture-password-only", first=True
    )
    return runtime, user


def test_browser_original_above_two_gib_is_admitted_without020(db, original):
    runtime, user = original
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": user["username"],
                "password": "synthetic-fixture-password-only",
            },
        )
        assert login.status_code == 200
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        response = client.post(
            "/api/video-uploads",
            json={
                "filename": "synthetic-valid-video.avi",
                "size": 2 * 1024**3 + 1,
                "request_id": uuid4().hex,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["expected_size"] == 2 * 1024**3 + 1
        too_large = client.post(
            "/api/video-uploads",
            json={
                "filename": "over-limit.avi",
                "size": 4 * 1024**3 + 1,
                "request_id": uuid4().hex,
            },
        )
        assert too_large.status_code == 413
        assert "4 GiB" in too_large.json()["detail"]
    with db.connection() as c:
        assert (
            c.execute("SELECT to_regclass('video_preview_jobs') AS x").fetchone()["x"]
            is None
        )
    assert MAX_CONTENT == 256 * 1024**2


def test_s3_explicit_original_bound_does_not_change_default_or_send_oversize(tmp_path):
    from video_service.object_store import S3ContentStore

    store = S3ContentStore(object(), "isolated-bucket", tmp_path, prefix="isolated")
    with pytest.raises(ValueError, match="Content size exceeded"):
        store.put("a" * 32, [b"x" * 33], "video", max_bytes=32)
    import inspect

    assert (
        inspect.signature(S3ContentStore.put).parameters["max_bytes"].default
        == MAX_CONTENT
    )


def test_large_completion_returns202_while_status_stays_readable(
    db, original, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from video_service.postgres.execution import Execution

    runtime, user = original
    owner = user["id"]
    row = runtime.upload_create(
        owner, "controlled-large.avi", 2 * 1024**3 + 1, uuid4().hex
    )
    # Control-plane fixture only: actual >2GiB transfer is a separate native journey.
    with db.connection() as c:
        c.execute(
            "UPDATE source_uploads SET uploaded_bytes=expected_size WHERE owner_id=%s AND id=%s",
            (owner, row["upload_id"]),
        )
    entered, release = Event(), Event()
    calls = []

    def finish(self, actor, identity):
        calls.append(identity)
        entered.set()
        assert release.wait(5)
        return self.upload_get(actor, identity)

    monkeypatch.setattr(Execution, "upload_complete", finish)
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": user["username"],
                "password": "synthetic-fixture-password-only",
            },
        )
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        with ThreadPoolExecutor(1) as pool:
            response = pool.submit(
                client.post,
                "/api/video-uploads/" + row["upload_id"] + "/complete",
                json={},
            )
            assert entered.wait(2)
            try:
                accepted = response.result(timeout=1)
                assert accepted.status_code == 202
                current = client.get("/api/video-uploads/" + row["upload_id"]).json()
                assert current["finalization_state"] in ("queued", "running")
                assert (
                    client.post(
                        "/api/video-uploads/" + row["upload_id"] + "/complete", json={}
                    ).status_code
                    == 202
                )
                assert len(calls) == 1
            finally:
                release.set()


def test_small_native_video_chunk_resume_register_shared_download_without_webm(
    db, original, tmp_path
):
    import subprocess

    runtime, user = original
    source = tmp_path / "small.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=2",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
    )
    data = source.read_bytes()
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app) as client:
        auth = client.post(
            "/api/auth/login",
            json={
                "username": user["username"],
                "password": "synthetic-fixture-password-only",
            },
        )
        client.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
        created = client.post(
            "/api/video-uploads",
            json={
                "filename": "small.mp4",
                "size": len(data),
                "request_id": "same-original-request",
            },
        )
        assert created.status_code == 201
        identity = created.json()["upload_id"]
        assert (
            client.post(
                "/api/video-uploads",
                json={
                    "filename": "small.mp4",
                    "size": len(data),
                    "request_id": "same-original-request",
                },
            ).json()["upload_id"]
            == identity
        )
        endpoint = "/api/video-uploads/" + identity
        for _ in range(2):
            response = client.put(
                endpoint + "/chunks?offset=0",
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 200
            assert response.json()["uploaded_bytes"] == len(data)
        assert (
            client.put(
                endpoint + "/chunks?offset=0",
                content=b"x" * len(data),
                headers={"Content-Type": "application/octet-stream"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                endpoint + "/verify",
                json={
                    "offset": 0,
                    "length": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "uploaded_bytes": len(data),
                },
            ).status_code
            == 204
        )
        done = client.post(endpoint + "/complete", json={})
        assert done.status_code == 200, done.text
        asset = done.json()["asset_id"]
        assert client.post(endpoint + "/complete", json={}).json()["asset_id"] == asset
        listing = client.get("/api/videos").json()["videos"]
        row = next(x for x in listing if x["asset_id"] == asset)
        assert row["sha256"] == hashlib.sha256(data).hexdigest()
        assert row["web_preview"]["status"] == "unavailable"
        assert client.get("/api/videos/" + asset + "/download").content == data
        assert client.get("/api/videos/" + asset + "/stream").status_code == 404
        other = Accounts(db).create(
            "other-fixture-user",
            "other-fixture-password",
            first=False,
            actor_id=user["id"],
        )
        client.post("/api/auth/logout", json={})
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": other["username"],
                    "password": "other-fixture-password",
                },
            ).status_code
            == 200
        )
        assert client.get("/api/videos/" + asset + "/download").content == data
    with db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM assets").fetchone()["n"] == 1
        assert (
            c.execute("SELECT count(*) AS n FROM source_upload_parts").fetchone()["n"]
            == 1
        )
        assert (
            c.execute("SELECT to_regclass('video_preview_jobs') AS x").fetchone()["x"]
            is None
        )


def test_resume_prefix_reads_only_overlapping_parts(db, original, monkeypatch):
    runtime, user = original
    owner = user["id"]
    row = runtime.upload_create(owner, "controlled.avi", 12, uuid4().hex)
    for offset, data in [(0, b"aaaa"), (4, b"bbbb"), (8, b"cccc")]:
        runtime.upload_chunk(owner, row["upload_id"], offset, data)
    reads = []
    original_path = runtime.store.path

    def path(actor, reference):
        reads.append(reference["sha256"])
        return original_path(actor, reference)

    monkeypatch.setattr(runtime.store, "path", path)
    runtime.upload_verify(
        owner,
        row["upload_id"],
        8,
        4,
        hashlib.sha256(b"cccc").hexdigest(),
        uploaded_bytes=12,
    )
    assert reads == [hashlib.sha256(b"cccc").hexdigest()]


def test_lost_original_guard_cannot_publish_but_same_upload_can_explicitly_retry(
    db, original, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import video_service.postgres.intake as intake_module

    runtime, user = original
    owner = user["id"]
    row = runtime.upload_create(owner, "controlled.avi", 8, uuid4().hex)
    runtime.upload_chunk(owner, row["upload_id"], 0, b"12345678")
    entered, release = Event(), Event()
    raw_put = runtime.store.put

    def gated(actor, blocks, kind, **kwargs):
        if kind == "video":
            entered.set()
            assert release.wait(5)
        return raw_put(actor, blocks, kind, **kwargs)

    monkeypatch.setattr(runtime.store, "put", gated)
    monkeypatch.setattr(
        intake_module, "probe", lambda p: {"duration": 1.0, "width": 16, "height": 16}
    )
    monkeypatch.setattr(
        intake_module,
        "process",
        lambda args, **kw: Path(args[-1]).write_bytes(b"controlled-thumbnail"),
    )
    key = "original-upload-complete:" + owner + ":" + row["upload_id"]
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(runtime.upload_complete, owner, row["upload_id"])
        assert entered.wait(3)
        with db.connection() as c:
            pid = c.execute(
                """WITH k AS(SELECT hashtextextended(current_schema()||%s,0) AS key)
                SELECT l.pid FROM pg_locks l,k WHERE l.locktype='advisory' AND l.granted
                AND l.objsubid=1 AND l.classid::bigint=((k.key>>32)&4294967295)
                AND l.objid::bigint=(k.key&4294967295)""",
                (key,),
            ).fetchone()["pid"]
            assert c.execute(
                "SELECT pg_terminate_backend(%s) AS yes", (pid,)
            ).fetchone()["yes"]
        release.set()
        with pytest.raises(psycopg.Error):
            pending.result(10)
    assert runtime.upload_get(owner, row["upload_id"])["asset_id"] is None
    with db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM assets").fetchone()["n"] == 0
        assert (
            c.execute("SELECT count(*) AS n FROM source_upload_parts").fetchone()["n"]
            == 1
        )
    assert runtime.upload_complete(owner, row["upload_id"])["asset_id"]


def test_original_completion_storage_does_not_hold_upload_row_lock(
    db, original, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import video_service.postgres.intake as intake_module

    runtime, user = original
    entered, release = Event(), Event()
    raw_put = runtime.store.put

    def gated(owner, blocks, kind, **kwargs):
        if kind == "video":
            entered.set()
            assert release.wait(5)
        return raw_put(owner, blocks, kind, **kwargs)

    monkeypatch.setattr(runtime.store, "put", gated)
    monkeypatch.setattr(
        intake_module, "probe", lambda p: {"duration": 1.0, "width": 16, "height": 16}
    )
    monkeypatch.setattr(
        intake_module,
        "process",
        lambda args, **kw: Path(args[-1]).write_bytes(b"controlled-thumbnail"),
    )
    owner = user["id"]
    row = runtime.upload_create(owner, "controlled.avi", 8, uuid4().hex)
    runtime.upload_chunk(owner, row["upload_id"], 0, b"12345678")
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(runtime.upload_complete, owner, row["upload_id"])
        assert entered.wait(3)
        try:
            with db.connection() as c:
                c.execute("SET LOCAL lock_timeout='100ms'")
                runtime._upload(c, owner, row["upload_id"], lock=True)
            with pytest.raises(ValueError, match="진행 중"):
                runtime.upload_complete(owner, row["upload_id"])
        finally:
            release.set()
        completed = pending.result(10)
    assert completed["asset_id"]
    assert (
        runtime.upload_complete(owner, row["upload_id"])["asset_id"]
        == completed["asset_id"]
    )
    with db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM assets").fetchone()["n"] == 1
        assert (
            c.execute("SELECT to_regclass('video_preview_jobs') AS x").fetchone()["x"]
            is None
        )
