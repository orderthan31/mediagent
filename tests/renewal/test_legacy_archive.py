"""Explicit disposable schema tests; DSN is read from the supplied private file."""

import json
import secrets
import unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.postgres import Database


class LegacyArchiveDatabaseTests(unittest.TestCase):
    def test_atomic_idempotent_import_and_admin_only_reads(self):
        from video_service.postgres.legacy_archive import LegacyArchive
        from video_service.postgres.accounts import Accounts
        from app.renewal import create_app
        from fastapi.testclient import TestClient

        dsn = Path("/run/bootstrap/database-dsn").read_text().strip()
        schema = "legacy_test_" + uuid4().hex
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        database = Database(make_conninfo(dsn, options="-c search_path=" + schema))
        try:
            database.migrate()
            manifest = {
                "version": 1,
                "namespace": "legacy/test",
                "index_counts": {},
                "records": [
                    {
                        "namespace": "legacy/test",
                        "kind": "job",
                        "record_id": "a" * 32,
                        "source_sha256": "b" * 64,
                        "classification": "legacy/unassigned",
                        "internal": True,
                        "legacy_state": "COMPLETED",
                        "payload": {"job_id": "a" * 32, "status": "COMPLETED"},
                        "references": [],
                    }
                ],
            }
            from video_service.legacy_archive import canonical
            import hashlib

            manifest["snapshot_id"] = hashlib.sha256(canonical(manifest)).hexdigest()
            archive = LegacyArchive(database)
            self.assertEqual(archive.apply(manifest, dry_run=True)["would_insert"], 1)
            self.assertEqual(archive.apply(manifest)["inserted"], 1)
            self.assertEqual(archive.apply(manifest)["inserted"], 0)
            self.assertEqual(archive.summary()["jobs"], 1)
            with database.connection() as connection:
                self.assertEqual(
                    connection.execute("SELECT count(*) AS n FROM jobs").fetchone()[
                        "n"
                    ],
                    0,
                )
            tampered = json.loads(json.dumps(manifest))
            tampered["records"][0]["source_sha256"] = "c" * 64
            tampered["snapshot_id"] = hashlib.sha256(
                canonical({k: v for k, v in tampered.items() if k != "snapshot_id"})
            ).hexdigest()
            with self.assertRaises(ValueError):
                archive.apply(tampered)
            accounts = Accounts(database)
            password = secrets.token_urlsafe(24)
            admin = accounts.create("archive-admin", password, first=True)
            accounts.create("archive-user", password, actor_id=admin["id"])
            app = create_app(
                database, allowed_origins=("http://testserver",), secure_cookies=False
            )
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/legacy/history").status_code, 401)
                self.assertEqual(
                    client.post(
                        "/api/auth/login",
                        json={"username": "archive-user", "password": password},
                    ).status_code,
                    200,
                )
                self.assertEqual(client.get("/api/legacy/history").status_code, 403)
            with TestClient(app) as client:
                self.assertEqual(
                    client.post(
                        "/api/auth/login",
                        json={"username": "archive-admin", "password": password},
                    ).status_code,
                    200,
                )
                response = client.get("/api/legacy/history")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["records"]), 1)
                self.assertEqual(
                    response.json()["records"][0]["classification"], "legacy/unassigned"
                )
        finally:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
