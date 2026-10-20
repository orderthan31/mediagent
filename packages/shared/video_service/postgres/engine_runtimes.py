"""CAS-pinned physical engine revisions. Logical provider/model refs stay separate."""

from psycopg.types.json import Jsonb
from video_service.cpu_agents import digest
from video_service.engine_protocol import validate_runtime


class EngineRuntimes:
    def __init__(self, database):
        self.database = database

    def register(self, descriptor, *, revision, enabled=False):
        validate_runtime(descriptor)
        if type(revision) is not int or revision < 0 or type(enabled) is not bool:
            raise ValueError("invalid_engine_revision")
        with self.database.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(764931011)")
            current = db.execute(
                "SELECT r.* FROM engine_runtime_heads h JOIN engine_runtime_revisions r USING (role,revision) WHERE role=%s",
                (descriptor["role"],),
            ).fetchone()
            if (current["revision"] if current else 0) != revision:
                raise ValueError("engine_revision_conflict")
            sha = digest(descriptor)
            if current and current["sha256"] == sha and current["enabled"] == enabled:
                return current
            next_revision = revision + 1
            row = db.execute(
                "INSERT INTO engine_runtime_revisions(role,revision,sha256,descriptor,enabled) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (descriptor["role"], next_revision, sha, Jsonb(descriptor), enabled),
            ).fetchone()
            db.execute(
                "INSERT INTO engine_runtime_heads(role,revision) VALUES (%s,%s) ON CONFLICT(role) DO UPDATE SET revision=excluded.revision",
                (descriptor["role"], next_revision),
            )
            return row

    def resolve(self, role, *, sha256=None):
        with self.database.connection() as db:
            return self.resolve_in(db, role, sha256=sha256)

    @staticmethod
    def resolve_in(db, role, *, sha256=None, lock=False):
        row = db.execute(
            "SELECT r.* FROM engine_runtime_heads h JOIN engine_runtime_revisions r USING (role,revision) WHERE role=%s"
            + (" FOR SHARE OF h" if lock else ""),
            (role,),
        ).fetchone()
        if (
            not row
            or not row["enabled"]
            or sha256 is not None
            and row["sha256"] != sha256
        ):
            raise ValueError("engine_unavailable_or_pin_changed")
        validate_runtime(row["descriptor"])
        if digest(row["descriptor"]) != row["sha256"]:
            raise ValueError("engine_descriptor_corrupt")
        return row
