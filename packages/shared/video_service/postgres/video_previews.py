"""Durable, deduplicated full-length derivative requests; HTTP does no media I/O."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from ..cpu_agents import digest
from . import Conflict, Missing
from .registry import resource_id
from .intake import Intake

FULL_PROFILE = {
    "id": "full-webm-vp9-opus-v1",
    "coverage": "full",
    "max_source_bytes": 4 * 1024**3,
    "max_duration_seconds": 6 * 3600,
    "max_pixels": 3840 * 2160,
    "max_output_bytes": 512 * 1024**2,
    "wall_seconds": 4 * 3600,
    "cache_bytes": 10 * 1024**3,
    "max_concurrency": 1,
    "max_queued": 32,
    "max_width": 960,
    "max_height": 720,
    "fps": 15,
}


class VideoPreviews:
    def __init__(self, runtime):
        self.runtime, self.database, self.store = (
            runtime,
            runtime.database,
            runtime.store,
        )

    def asset_source(self, db, identity):
        row = self.runtime._shared_asset(db, identity)
        reference = Intake.asset_reference(row)
        media = row["metadata"].get("media") or {}
        return (
            {
                "kind": "asset",
                "asset_id": row["id"],
                "media": {
                    key: media.get(key) for key in ("duration", "width", "height")
                },
            },
            row["owner_id"],
            reference,
        )

    @staticmethod
    def supported(source):
        subject, _, reference = source
        if not 0 < reference["bytes"] <= FULL_PROFILE["max_source_bytes"]:
            return False
        if subject["kind"] == "asset":
            media = subject["media"]
            return (
                type(media["duration"]) in (float, int)
                and 0 < media["duration"] <= FULL_PROFILE["max_duration_seconds"]
                and type(media["width"]) is int
                and type(media["height"]) is int
                and 0 < media["width"] <= 4096
                and 0 < media["height"] <= 4096
                and media["width"] * media["height"] <= FULL_PROFILE["max_pixels"]
            )
        return True

    @staticmethod
    def public(row):
        return {
            "id": row["id"],
            "state": row["state"],
            "coverage": "full",
            "cancel_requested": row["cancel_requested"],
            "profile": row["profile"],
            "stage": row.get("stage", row["state"]),
            "download_url": "/api/video-previews/" + row["id"] + "/file"
            if row["state"] == "ready"
            else None,
            "source_sha256": row["source_ref"]["sha256"],
            "error_code": row["error_code"],
            "media": row["output_media"] if row["state"] == "ready" else None,
            **(
                {
                    "sha256": row["output_ref"]["sha256"],
                    "bytes": row["output_ref"]["bytes"],
                }
                if row["state"] == "ready"
                else {}
            ),
        }

    def enqueue_in(self, db, actor, source, *, automatic=False):
        subject, owner, reference = source
        key = digest(
            {
                "subject": subject,
                "owner": owner,
                "source": reference,
                "profile": FULL_PROFILE,
            }
        )
        db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('full-preview-admission',0))"
        )
        previous = db.execute(
            "SELECT * FROM video_preview_jobs WHERE request_key=%s", (key,)
        ).fetchone()
        if previous:
            return self.public(previous)
        supported = self.supported(source)
        if not supported and not automatic:
            raise ValueError("Full preview input budget exceeded")
        full = (
            db.execute(
                "SELECT count(*) AS n FROM video_preview_jobs WHERE state IN ('queued','running')"
            ).fetchone()["n"]
            >= FULL_PROFILE["max_queued"]
        )
        if full and not automatic:
            raise Conflict("Full preview queue capacity reached")
        row = db.execute(
            "INSERT INTO video_preview_jobs(id,request_key,requested_by,storage_owner_id,subject,source_ref,profile,state,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4().hex,
                key,
                actor,
                owner,
                Jsonb(subject),
                Jsonb(reference),
                Jsonb(FULL_PROFILE),
                "failed" if full or not supported else "queued",
                "preview_input_budget"
                if not supported
                else "preview_queue_capacity"
                if full
                else None,
            ),
        ).fetchone()
        return self.public(row)

    def request_asset(self, actor, identity):
        with self.database.connection() as db:
            return self.enqueue_in(db, actor, self.asset_source(db, identity))

    def artifact_source(self, db, job_id, run_id, port):
        from .ticket_artifacts import TicketArtifacts

        jobs = db.execute(
            "SELECT * FROM jobs WHERE id=%s LIMIT 2", (resource_id(job_id),)
        ).fetchall()
        if not jobs:
            raise Missing("Accepted preview ticket not found")
        if len(jobs) != 1:
            raise Conflict("Ambiguous preview ticket")
        job = jobs[0]
        if digest(job["snapshot"]) != job["snapshot_sha256"]:
            raise Conflict("Preview ticket snapshot changed")
        run = db.execute(
            "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s AND status='completed' AND generation=%s",
            (job["owner_id"], job["id"], resource_id(run_id), job["generation"]),
        ).fetchone()
        if job["cancel_requested"] or job["status"] == "cancelled" or not run:
            raise Missing("Normal accepted video is not available")
        entries = TicketArtifacts(self.store).entries(job, [run])
        matches = [
            x
            for x in entries
            if x["output_port"] == port and x["reference"]["type"] == "video"
        ]
        if len(matches) != 1:
            raise Missing("Accepted video output not found")
        entry = matches[0]
        if not 0 < entry["storage"]["bytes"] <= FULL_PROFILE["max_source_bytes"]:
            raise ValueError("Full preview source exceeds its separate budget")
        subject = {
            "kind": "artifact",
            "ticket_id": job["id"],
            "node_id": run["node_id"],
            "attempt_id": run["id"],
            "attempt": run["attempt"],
            "generation": run["generation"],
            "output_port": port,
            "snapshot_sha256": job["snapshot_sha256"],
            "accepted_receipt_sha256": digest(run["result"]),
        }
        return subject, job["owner_id"], entry["storage"]

    def request_artifact(self, actor, job_id, run_id, port):
        with self.database.connection() as db:
            return self.enqueue_in(
                db, actor, self.artifact_source(db, job_id, run_id, port)
            )

    def binding_matches(self, db, row):
        try:
            subject, owner, reference = (
                self.asset_source(db, row["subject"]["asset_id"])
                if row["subject"]["kind"] == "asset"
                else self.artifact_source(
                    db,
                    row["subject"]["ticket_id"],
                    row["subject"]["attempt_id"],
                    row["subject"]["output_port"],
                )
            )
            return (subject, owner, reference) == (
                row["subject"],
                row["storage_owner_id"],
                row["source_ref"],
            )
        except (ValueError, Missing, Conflict, KeyError):
            return False

    def get(self, actor, identity):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s", (resource_id(identity),)
            ).fetchone()
            if row is None:
                raise Missing("Full preview request not found")
            if not self.binding_matches(db, row):
                row = {**row, "state": "held", "error_code": "preview_source_changed"}
            user = db.execute(
                "SELECT role FROM accounts WHERE id=%s", (actor,)
            ).fetchone()
            return {
                **self.public(row),
                "can_cancel": row["state"] in ("queued", "running", "ready")
                and (
                    actor in (row["requested_by"], row["storage_owner_id"])
                    or bool(user and user["role"] == "admin")
                ),
            }

    def file(self, actor, identity):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s", (resource_id(identity),)
            ).fetchone()
            if (
                row is None
                or row["state"] != "ready"
                or row["cancel_requested"]
                or not self.binding_matches(db, row)
            ):
                raise Missing("Verified full preview is not ready")
        path = self.store.path(row["storage_owner_id"], row["output_ref"])
        with self.database.connection() as db:
            current = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s", (row["id"],)
            ).fetchone()
            if (
                current is None
                or current["state"] != "ready"
                or current["cancel_requested"]
                or current["output_ref"] != row["output_ref"]
                or not self.binding_matches(db, current)
            ):
                raise Missing("Full preview changed during storage verification")
        return path

    def asset_status(self, actor, identity):
        with self.database.connection() as db:
            subject, owner, reference = self.asset_source(db, identity)
            key = digest(
                {
                    "subject": subject,
                    "owner": owner,
                    "source": reference,
                    "profile": FULL_PROFILE,
                }
            )
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE request_key=%s", (key,)
            ).fetchone()
        return (
            self.get(actor, row["id"])
            if row
            else {"state": "not_requested", "coverage": "full", "profile": FULL_PROFILE}
        )

    def cancel(self, actor, identity):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE id=%s FOR UPDATE",
                (resource_id(identity),),
            ).fetchone()
            if row is None:
                raise Missing("Full preview request not found")
            user = db.execute(
                "SELECT role,active FROM accounts WHERE id=%s", (actor,)
            ).fetchone()
            if (
                not user
                or not user["active"]
                or (
                    actor not in (row["requested_by"], row["storage_owner_id"])
                    and user["role"] != "admin"
                )
            ):
                raise Conflict("Full preview cancellation is not authorized")
            state = (
                "cancelled"
                if row["state"] in ("queued", "ready", "failed")
                else row["state"]
            )
            row = db.execute(
                "UPDATE video_preview_jobs SET cancel_requested=true,state=%s,finished_at=CASE WHEN %s='cancelled' THEN now() ELSE finished_at END WHERE id=%s RETURNING *",
                (state, state, row["id"]),
            ).fetchone()
            return self.public(row)

    def artifact_status(self, actor, job_id, run_id, port):
        with self.database.connection() as db:
            subject, owner, reference = self.artifact_source(db, job_id, run_id, port)
            key = digest(
                {
                    "subject": subject,
                    "owner": owner,
                    "source": reference,
                    "profile": FULL_PROFILE,
                }
            )
            row = db.execute(
                "SELECT * FROM video_preview_jobs WHERE request_key=%s", (key,)
            ).fetchone()
        return (
            self.get(actor, row["id"])
            if row
            else {"state": "not_requested", "coverage": "full", "profile": FULL_PROFILE}
        )
