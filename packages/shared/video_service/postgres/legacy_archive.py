"""Immutable, administrator-only archive; never produces executable renewal jobs."""

import hashlib
from psycopg.types.json import Jsonb
from video_service.legacy_archive import canonical, sanitized


class LegacyArchive:
    def __init__(self, database):
        self.database = database

    def apply(self, manifest, *, dry_run=False):
        body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
        if manifest["snapshot_id"] != hashlib.sha256(canonical(body)).hexdigest():
            raise ValueError("legacy_snapshot_digest_mismatch")
        inserted = unchanged = 0
        with self.database.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(764931010)")
            if not dry_run:
                db.execute(
                    "INSERT INTO legacy_import_snapshots(snapshot_id,namespace,index_counts) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        manifest["snapshot_id"],
                        manifest["namespace"],
                        Jsonb(manifest["index_counts"]),
                    ),
                )
            for record in manifest["records"]:
                if (
                    record["classification"] != "legacy/unassigned"
                    or sanitized(record["payload"]) != record["payload"]
                ):
                    raise ValueError("unsafe_legacy_payload")
                digest = hashlib.sha256(canonical(record)).hexdigest()
                key = (record["namespace"], record["kind"], record["record_id"])
                previous = db.execute(
                    "SELECT content_sha256 FROM legacy_archive_records WHERE namespace=%s AND kind=%s AND record_id=%s",
                    key,
                ).fetchone()
                if previous:
                    if previous["content_sha256"] != digest:
                        raise ValueError("legacy_record_conflict_preserve_existing")
                    unchanged += 1
                    continue
                inserted += 1
                if not dry_run:
                    db.execute(
                        "INSERT INTO legacy_archive_records(namespace,kind,record_id,source_sha256,content_sha256,snapshot_id,classification,internal,legacy_state,payload,artifact_references) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            *key,
                            record["source_sha256"],
                            digest,
                            manifest["snapshot_id"],
                            record["classification"],
                            record["internal"],
                            record["legacy_state"],
                            Jsonb(record["payload"]),
                            Jsonb(record["references"]),
                        ),
                    )
        return {
            "snapshot_id": manifest["snapshot_id"],
            "inserted": 0 if dry_run else inserted,
            "would_insert": inserted,
            "unchanged": unchanged,
            "dry_run": dry_run,
        }

    def summary(self):
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT kind,legacy_state,internal,count(*) AS count FROM legacy_archive_records GROUP BY kind,legacy_state,internal"
            ).fetchall()
        return {
            "classification": "legacy/unassigned",
            "read_only": True,
            "jobs": sum(row["count"] for row in rows if row["kind"] == "job"),
            "groups": rows,
        }

    def records(self, *, kind="job", limit=100, offset=0):
        if (
            kind not in {"job", "index", "workflow", "settings", "asset"}
            or not 1 <= limit <= 200
            or offset < 0
        ):
            raise ValueError("invalid_archive_query")
        with self.database.connection() as db:
            rows = db.execute(
                "SELECT namespace,kind,record_id,source_sha256,classification,internal,legacy_state,payload,artifact_references FROM legacy_archive_records WHERE kind=%s ORDER BY namespace,record_id LIMIT %s OFFSET %s",
                (kind, limit, offset),
            ).fetchall()
            count = db.execute(
                "SELECT count(*) AS n FROM legacy_archive_records WHERE kind=%s",
                (kind,),
            ).fetchone()["n"]
        return {
            "classification": "legacy/unassigned",
            "read_only": True,
            "total": count,
            "records": rows,
        }
