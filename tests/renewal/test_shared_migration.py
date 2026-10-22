"""Late 012 application after an already-applied 018, disposable PG only."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

import video_service.postgres as postgres
from video_service.content_store import ContentStore
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from test_execution import graph, movie as movie


def test_late_origin_migration_preserves_legacy_snapshot_and_owner(movie, tmp_path, monkeypatch):
    assert os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
    dsn = os.environ["MIDEAGENT_TEST_DSN"]
    schema = "shared_upgrade_" + uuid4().hex
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(make_conninfo(dsn, options="-c search_path=" + schema))
    try:
        # Build the exact installed migration chain excluding not-yet-operating 012.
        with db.connection() as c:
            c.execute("CREATE TABLE schema_migrations (name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())")
            for path in sorted((Path(postgres.__file__).parent / "migrations").glob("*.sql")):
                if path.name == "012_shared_asset_origin.sql":
                    continue
                raw = path.read_bytes()
                c.execute(raw.decode())
                c.execute("INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)", (path.name, hashlib.sha256(raw).hexdigest()))
        import secrets
        a = Accounts(db).create("migration-uploader", secrets.token_urlsafe(24), first=True)
        b = Accounts(db).create("migration-executor", secrets.token_urlsafe(24), actor_id=a["id"])
        (tmp_path / "cas").mkdir()
        runtime = Execution(db, ContentStore(tmp_path / "cas"))
        source = runtime.ingest(a["id"], "legacy-shared.mp4", movie)
        definition_id = uuid4().hex
        saved = runtime.save_definition(a["id"], definition_id, graph("encode"))
        import video_service.postgres.execution as execution_module
        serializer = execution_module.public_asset
        # Simulate the old serializer before INSERT; keep all immutability triggers enabled.
        with monkeypatch.context() as patch:
            patch.setattr(execution_module, "public_asset", lambda row: {k:v for k,v in serializer(row).items() if k != "uploaded_by"})
            legacy = runtime.create(a["id"], source["asset_id"], definition_id, saved["revision"], request_id=uuid4().hex)
        assert "uploaded_by" not in legacy["snapshot"]["asset"]
        with db.connection() as c:
            before_job = dict(c.execute("SELECT * FROM jobs WHERE id=%s", (legacy["id"],)).fetchone())
            before_assets = c.execute("SELECT * FROM assets ORDER BY id").fetchall()
        assert db.migrate() == ["012_shared_asset_origin.sql"]
        assert db.migrate() == []
        with db.connection() as c:
            after_job = dict(c.execute("SELECT * FROM jobs WHERE id=%s", (legacy["id"],)).fetchone())
            assert after_job.pop("asset_owner_id") == a["id"]
            assert after_job == before_job
            assert c.execute("SELECT * FROM assets ORDER BY id").fetchall() == before_assets
        child = runtime.create(b["id"], source["asset_id"], definition_id, saved["revision"], request_id=uuid4().hex)
        assert child["owner_id"] == b["id"] and child["asset_owner_id"] == a["id"]
        assert child["snapshot"]["inputs"]["video"]["source_owner_id"] == a["id"]
        assert runtime.asset_path(b["id"], source["asset_id"]).read_bytes() == movie
        assert not (runtime.store.owner_root(b["id"]) / child["snapshot"]["inputs"]["video"]["storage_key"]).exists()
    finally:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
