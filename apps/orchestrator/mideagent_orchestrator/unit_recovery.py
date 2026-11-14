"""Explicit application authority for an unresolved model node's user recovery.

This is not an old worker result and does not renew its expired lease, rewrite its
held packet, dispatch a following node, or issue any provider request.
"""
from uuid import uuid4

from psycopg.types.json import Jsonb

from video_service.canonical import digest
from video_service.postgres import Conflict, Missing
from video_service.postgres.model_call_fence import model_call_fence


def accept_role_recovery(runtime, owner, job_id, run_id, request_id):
    from video_service.postgres.unit_recovery import RoleUnitRecovery

    service = RoleUnitRecovery(runtime)
    prepared = service.prepare_adoption(owner, job_id, run_id, request_id)
    recovery_id = prepared["recovery_id"]
    context = prepared["context_sha256"]
    command = prepared["command"]
    if command["run_id"] != job_id or command["attempt_id"] != run_id:
        raise Conflict("unit_recovery_command_scope_changed")
    # Existing immutable CPU/source/ticket ownership checks, never lease renewal.
    verified = runtime._preflight_cpu_inputs(owner, job_id, command)
    with model_call_fence(runtime.database, owner, job_id):
        with runtime.database.connection() as db:
            job = runtime._job(db, owner, job_id, lock=True)
            run = db.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE",
                (owner, job_id, run_id),
            ).fetchone()
            if not run:
                raise Missing("unit_recovery_source_run_missing")
            recovery = service.check_adoption_in(
                db, owner, job, run, recovery_id, context
            )
            existing = (run.get("result") or {}).get("unit_recovery", {})
            if recovery["status"] == "applied":
                if (run["status"] != "completed" or existing.get("id") != recovery_id
                        or digest(run["result"]) != recovery["receipt_sha256"]):
                    raise Conflict("unit_recovery_applied_receipt_changed")
                inbox = db.execute(
                    "SELECT payload_sha256 FROM message_inbox WHERE consumer=%s AND message_id=%s",
                    ("result:" + owner, run_id),
                ).fetchone()
                if not inbox or inbox["payload_sha256"] != recovery["receipt_sha256"]:
                    raise Conflict("unit_recovery_applied_inbox_changed")
                return runtime._view(db, job)
            if (
                job["cancel_requested"]
                or job["status"] not in {"waiting", "running"}
                or run["status"] != "running"
                or job["generation"] != run["generation"]
                or job["generation"] != command["generation"]
                or not job["active_claim_id"]
                or job["active_claim_id"] != run["claim_id"]
                or run["request_sha256"] != digest(command)
                or run["request"] != command
                or run.get("result") is not None
            ):
                raise Conflict("unit_recovery_source_attempt_changed")
            if db.execute(
                "SELECT 1 FROM message_inbox WHERE consumer=%s AND message_id=%s",
                ("result:" + owner, run_id),
            ).fetchone():
                raise Conflict("unit_recovery_original_result_already_accepted")
            if db.execute(
                "SELECT 1 FROM result_quarantine WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (owner, job_id, run_id),
            ).fetchone():
                raise Conflict("unit_recovery_quarantined_result_requires_review")
            for reference in command["inputs"].values():
                runtime._checked_input(owner, job, reference, verified)
            outputs = prepared["outputs"]
            if not outputs:
                raise Conflict("unit_recovery_empty_output_not_supported")
            for reference in outputs.values():
                runtime.store.path(owner, reference)
            metadata = prepared.get("receipt_metadata", {})
            receipt = {
                **{key: command[key] for key in (
                    "protocol_version", "run_id", "attempt_id", "generation", "agent"
                )},
                "request_sha256": run["request_sha256"],
                "status": "completed",
                "transport": "application_unit_recovery",
                "outputs": outputs,
                "previews": {},
                **{key: metadata[key] for key in ("transcription", "translation") if key in metadata},
                "unit_recovery": {
                    **metadata.get("unit_recovery", {}),
                    "version": 1,
                    "id": recovery_id,
                    "source_task_id": prepared["task_row"]["task_id"],
                    "source_result_sha256": prepared["task_row"].get("result_sha256"),
                    "context_sha256": context,
                    "resolution_origin": "explicit_user_decisions",
                },
            }
            receipt = runtime.ticket_artifacts.capture(db, job, run, receipt)
            receipt_sha256 = digest(receipt)
            db.execute(
                "UPDATE node_runs SET status='completed',result=%s,completed_at=now(),lease_owner=NULL WHERE owner_id=%s AND job_id=%s AND id=%s AND status='running'",
                (Jsonb(receipt), owner, job_id, run_id),
            )
            for port, reference in outputs.items():
                if runtime.ticket_artifacts.enabled(job):
                    reference = next(
                        entry["storage"] for entry in receipt["ticket_artifacts"]["entries"]
                        if entry["output_port"] == port
                    )
                db.execute(
                    "INSERT INTO artifacts(owner_id,job_id,node_run_id,id,type,storage_key,bytes,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (owner, job_id, run_id, uuid4().hex, reference["type"],
                     reference["storage_key"], reference["bytes"], reference["sha256"]),
                )
            # Fence late ordinary replies before their stale/quarantine side effects.
            # The receipt explicitly names recovery authority, never a forged worker.
            db.execute(
                "INSERT INTO message_inbox(consumer,message_id,payload_sha256) VALUES (%s,%s,%s)",
                ("result:" + owner, run_id, receipt_sha256),
            )
            service.mark_applied_in(db, recovery_id, receipt_sha256)
            runtime._write_outbox(db, owner, job_id, "agent.result.accepted.v1", {
                "job_id": job_id, "node_run_id": run_id,
                "generation": run["generation"], "quarantined": False,
                "unit_recovery_id": recovery_id,
            })
            db.execute(
                "UPDATE jobs SET revision=revision+1,updated_at=now() WHERE owner_id=%s AND id=%s",
                (owner, job_id),
            )
            return runtime._view(db, runtime._job(db, owner, job_id))
