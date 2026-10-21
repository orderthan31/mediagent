"""Status-only persistence. Never changes workflow jobs, results, claims or keys."""

from datetime import datetime

from ..worker_telemetry import validate_report

TTL_SECONDS = 15


def view(row):
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}


class WorkerTelemetry:
    def __init__(self, database):
        self.database = database

    def beat(self):
        with self.database.connection() as db:
            db.execute("INSERT INTO telemetry_observer(singleton,received_at) VALUES (true,now()) "
                       "ON CONFLICT(singleton) DO UPDATE SET received_at=now()")

    def accept(self, report, source_exchange, *, expected_worker_id):
        validate_report(report, source_exchange)
        if report["worker_id"] != expected_worker_id:
            raise ValueError("telemetry_worker_binding_mismatch")
        with self.database.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("worker-status:" + expected_worker_id,))
            previous = db.execute("SELECT * FROM worker_observations WHERE worker_id=%s FOR UPDATE", (expected_worker_id,)).fetchone()
            if previous:
                if previous["family"] != report["family"] or previous["role"] != report["role"]:
                    raise ValueError("telemetry_worker_role_mismatch")
                if report["boot_id"] < previous["boot_id"] or (
                    report["boot_id"] == previous["boot_id"] and report["sequence"] <= previous["sequence"]
                ):
                    return False
            transition = previous is None or any(previous[k] != report[k] for k in ("boot_id", "state", "ticket_id", "attempt_id"))
            db.execute(
                "INSERT INTO worker_observations(worker_id,family,role,boot_id,sequence,state,ticket_id,attempt_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(worker_id) DO UPDATE SET "
                "boot_id=excluded.boot_id,sequence=excluded.sequence,state=excluded.state,ticket_id=excluded.ticket_id,"
                "attempt_id=excluded.attempt_id,received_at=now()",
                tuple(report[k] for k in ("worker_id", "family", "role", "boot_id", "sequence", "state", "ticket_id", "attempt_id")),
            )
            if transition:
                db.execute(
                    "INSERT INTO worker_observation_events(worker_id,boot_id,sequence,state,ticket_id,attempt_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    tuple(report[k] for k in ("worker_id", "boot_id", "sequence", "state", "ticket_id", "attempt_id")),
                )
        return True

    def role(self, role):
        with self.database.connection() as db:
            observer = db.execute("SELECT received_at, received_at>now()-interval '15 seconds' AS healthy FROM telemetry_observer WHERE singleton=true").fetchone()
            collector = view(observer) if observer else {"received_at": None, "healthy": False}
            rows = db.execute(
                "SELECT w.*, w.received_at>now()-interval '15 seconds' AS fresh,r.node_id,j.ticket_number "
                "FROM worker_observations w LEFT JOIN node_runs r ON r.id=w.attempt_id AND r.job_id=w.ticket_id AND r.node_type=w.role "
                "AND COALESCE(r.request->'agent'->>'family','cpu')=w.family "
                "LEFT JOIN jobs j ON j.id=r.job_id WHERE w.role=%s ORDER BY w.family,w.worker_id", (role,)
            ).fetchall()
            workers = []
            for row in rows:
                worker = view(row)
                worker["reported_state"] = worker["state"]
                if not collector["healthy"]:
                    worker["state"] = "unknown"
                elif not worker.pop("fresh") and worker["state"] != "stopped":
                    worker["state"] = "heartbeat_lost"
                worker.pop("fresh", None)
                worker["recent_events"] = [view(r) for r in db.execute(
                    "SELECT e.state,e.ticket_id,e.attempt_id,e.received_at,r.node_id,j.ticket_number "
                    "FROM worker_observation_events e LEFT JOIN node_runs r ON r.id=e.attempt_id AND r.job_id=e.ticket_id "
                    "LEFT JOIN jobs j ON j.id=r.job_id WHERE e.worker_id=%s ORDER BY e.received_at DESC,e.sequence DESC LIMIT 8",
                    (worker["worker_id"],)
                ).fetchall()]
                workers.append(worker)
        return {"collector": collector, "workers": workers, "ttl_seconds": TTL_SECONDS}
