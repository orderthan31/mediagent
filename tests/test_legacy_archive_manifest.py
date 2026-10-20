from contextlib import closing
import os
import json
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path


class LegacyArchiveManifestTests(unittest.TestCase):
    def test_unassigned_manifest_keeps_namespaces_and_removes_secrets(self):
        from video_service.legacy_archive import build_manifest

        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            root = Path(directory) / "jobs"
            indexes = Path(directory) / "indexes"
            indexes.mkdir()
            job_id = "a" * 32
            job = {
                "job_id": job_id,
                "status": "COMPLETED",
                "metadata": {"internal": True, "api_key": secrets.token_hex(32)},
            }
            path = root / job_id
            path.mkdir(parents=True)
            (path / "job.json").write_text(json.dumps(job), encoding="utf-8")
            (path / "output.mp4").write_bytes(b"independent-fixture-artifact")
            for name, value in [
                ("primary", job),
                ("secondary", {**job, "status": "FAILED"}),
            ]:
                with closing(sqlite3.connect(indexes / (name + ".sqlite3"))) as db:
                    db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, data TEXT)")
                    db.execute(
                        "INSERT INTO jobs VALUES (?,?)", (job_id, json.dumps(value))
                    )
                    db.commit()
            result = build_manifest(root, indexes, namespace="legacy/test")
            history = [row for row in result["records"] if row["kind"] == "job"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["classification"], "legacy/unassigned")
            self.assertTrue(history[0]["internal"])
            self.assertEqual(history[0]["legacy_state"], "COMPLETED")
            self.assertNotIn(job["metadata"]["api_key"], json.dumps(result))
            self.assertEqual(
                result["index_counts"], {"primary.sqlite3": 1, "secondary.sqlite3": 1}
            )
            self.assertEqual(
                len([row for row in result["records"] if row["kind"] == "index"]), 2
            )
            self.assertTrue(history[0]["references"])
            self.assertEqual(
                result, build_manifest(root, indexes, namespace="legacy/test")
            )


if __name__ == "__main__":
    unittest.main()
