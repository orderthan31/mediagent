"""Durable processing uncertainty, distinct from native lifecycle recovery.

System observations fence old scheduling, never reset or rewrite source facts.
Only an administrator's separately bound decision may create a new draft child.
"""

import json

from uuid import uuid4
from psycopg.types.json import Jsonb
from ..cpu_agents import digest as content_digest
from . import Conflict, Missing
from .control_recovery import admin, digest, identity, public


def payload(value):
    return Jsonb(value, dumps=lambda v: json.dumps(v, default=public))


class JobProcessingReview:
    def __init__(self, runtime):
        self.runtime, self.database = runtime, runtime.database

    @staticmethod
    def blocked_in(db, owner, job):
        return bool(
            db.execute(
                "SELECT 1 FROM job_processing_cases WHERE owner_id=%s AND job_id=%s",
                (owner, job),
            ).fetchone()
        )

    @staticmethod
    def _context(db, job, run):
        owner, jid = job["owner_id"], job["id"]
        q = db.execute(
            "SELECT * FROM broker_dispatch_queue WHERE node_run_id=%s", (run["id"],)
        ).fetchone()
        out = db.execute(
            "SELECT id,message_type,payload,published_at,created_at FROM message_outbox WHERE id=%s AND owner_id=%s AND aggregate_id=%s",
            (run["id"], owner, jid),
        ).fetchone()
        events = [
            dict(r)
            for r in db.execute(
                "SELECT worker_id,boot_id,sequence,state,ticket_id,attempt_id,received_at FROM worker_observation_events WHERE ticket_id=%s AND attempt_id=%s ORDER BY received_at,sequence",
                (jid, run["id"]),
            ).fetchall()
        ]
        late = [
            dict(r)
            for r in db.execute(
                "SELECT message_sha256,verified,outputs,error_code,received_at,result FROM job_processing_late_results WHERE case_id=(SELECT id FROM job_processing_cases WHERE owner_id=%s AND job_id=%s) ORDER BY received_at,message_sha256",
                (owner, jid),
            ).fetchall()
        ]
        group = db.execute(
            "SELECT agent_id,capacity,slot_ids,observed,observed_at>now()-interval '15 seconds' AS fresh FROM remote_control_groups WHERE agent_id='encode'"
        ).fetchone()
        group_context = None
        if group:
            group_context = {
                k: group[k] for k in ("agent_id", "capacity", "slot_ids", "fresh")
            }
            group_context["workers"] = (
                [
                    {k: w.get(k) for k in ("id", "boot_id", "running", "state")}
                    for w in group["observed"]
                ]
                if group["observed"] is not None
                else None
            )
            group_context["transitions"] = [
                dict(r)
                for r in db.execute(
                    "SELECT worker_id,count(*) AS count,max(received_at) AS last_transition FROM worker_observation_events WHERE worker_id=ANY(%s) GROUP BY worker_id",
                    (group["slot_ids"],),
                ).fetchall()
            ]
        return {
            "job": {
                k: job[k]
                for k in (
                    "owner_id",
                    "id",
                    "status",
                    "revision",
                    "generation",
                    "active_claim_id",
                    "snapshot_sha256",
                    "cancel_requested",
                )
            },
            "attempt": dict(run),
            "other_attempts": [
                dict(r)
                for r in db.execute(
                    "SELECT n.id,n.node_id,n.node_type,n.status,n.generation,n.claim_id,n.attempt,n.iteration,n.request_sha256,n.result,n.lease_expires_at,n.started_at,n.completed_at,q.phase AS dispatch_phase,q.release_decision_id FROM node_runs n LEFT JOIN broker_dispatch_queue q ON q.owner_id=n.owner_id AND q.job_id=n.job_id AND q.node_run_id=n.id WHERE n.owner_id=%s AND n.job_id=%s AND n.id<>%s ORDER BY n.id",
                    (owner, jid, run["id"]),
                ).fetchall()
            ],
            "outbox": dict(out) if out else None,
            "dispatch": dict(q) if q else None,
            "worker_events": events,
            "quarantined_results": late,
            "execution_target": group_context,
            "inbox": [
                dict(r)
                for r in db.execute(
                    "SELECT consumer,message_id,payload_sha256,received_at FROM message_inbox WHERE consumer=%s AND message_id=%s",
                    ("result:" + owner, run["id"]),
                ).fetchall()
            ],
        }

    def capture_in(self, db, job):
        row = db.execute(
            "SELECT * FROM job_processing_cases WHERE owner_id=%s AND job_id=%s FOR UPDATE",
            (job["owner_id"], job["id"]),
        ).fetchone()
        if row:
            return self.projection(row)
        if job["status"] not in (
            "running",
            "waiting",
            "failed",
            "cancelled",
            "cancelling",
        ):
            return None
        # Lease creation/expiry share the database clock, even on separate hosts.
        db_now = db.execute("SELECT now() AS instant").fetchone()["instant"]
        for run in self.runtime._runs(db, job["owner_id"], job["id"]):
            if run["node_type"] != "encode":
                continue
            q = db.execute(
                "SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s",
                (run["id"],),
            ).fetchone()
            cause = (
                "dispatch_unknown"
                if q and q["phase"] == "unknown"
                else "legacy_lease_expired"
                if not q
                and job["status"] == "running"
                and run["status"] == "running"
                and (
                    run["lease_expires_at"] is None or run["lease_expires_at"] < db_now
                )
                else None
            )
            if not cause:
                continue
            evidence = self._context(db, job, run)
            sha = digest(evidence)
            row = db.execute(
                "INSERT INTO job_processing_cases(id,owner_id,job_id,node_run_id,cause,evidence_sha256) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,job_id) DO NOTHING RETURNING *",
                (uuid4().hex, job["owner_id"], job["id"], run["id"], cause, sha),
            ).fetchone()
            if row:
                db.execute(
                    "INSERT INTO job_processing_observations(case_id,revision,evidence_sha256,evidence) VALUES(%s,1,%s,%s)",
                    (row["id"], sha, payload(evidence)),
                )
            else:
                row = db.execute(
                    "SELECT * FROM job_processing_cases WHERE owner_id=%s AND job_id=%s",
                    (job["owner_id"], job["id"]),
                ).fetchone()
            return self.projection(row)
        return None

    @staticmethod
    def projection(row):
        return {
            "case_id": row["id"],
            "state": row["state"],
            "revision": row["revision"],
            "cause": row["cause"],
            "source_attempt_id": row["node_run_id"],
            "child_id": row["child_id"],
            "label": "새 복구 작업 연결됨 · 원 기록 보존"
            if row["child_id"]
            else "처리 여부 확인 필요",
        }

    def _locked(self, db, job_id):
        identity(job_id)
        rows = db.execute(
            "SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job_id,)
        ).fetchall()
        if len(rows) != 1:
            raise Missing("job_missing_or_ambiguous")
        job = rows[0]
        self.runtime._job(db, job["owner_id"], job_id)
        self.capture_in(db, job)
        case = db.execute(
            "SELECT * FROM job_processing_cases WHERE owner_id=%s AND job_id=%s FOR UPDATE",
            (job["owner_id"], job_id),
        ).fetchone()
        if not case:
            raise Conflict("processing_confirmation_not_required")
        run = db.execute(
            "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
            (job["owner_id"], job_id, case["node_run_id"]),
        ).fetchone()
        evidence = self._context(db, job, run)
        sha = digest(evidence)
        if sha != case["evidence_sha256"]:
            case = db.execute(
                "UPDATE job_processing_cases SET evidence_sha256=%s,revision=revision+1 WHERE id=%s RETURNING *",
                (sha, case["id"]),
            ).fetchone()
            db.execute(
                "INSERT INTO job_processing_observations(case_id,revision,evidence_sha256,evidence) VALUES(%s,%s,%s,%s)",
                (case["id"], case["revision"], sha, payload(evidence)),
            )
        return job, case, run, evidence

    def _eligibility(self, db, job, case, run, evidence):
        from .dispatch_queue import DispatchQueue

        reasons = []
        if case["child_id"]:
            reasons.append("child_already_created")
        nodes = job["snapshot"]["definition"]["nodes"]
        if (
            job["snapshot"]["model_bindings"]
            or len(nodes) != 1
            or nodes[0]["type"] != "encode"
        ):
            reasons.append("single_encode_scope_required")
        # A receipt for this attempt never proves another attempt has terminated.
        # Non-success/cancel flags alone are not positive termination evidence.
        if any(
            other["status"] != "completed"
            or not isinstance(other["result"], dict)
            or other["result"].get("status") != "completed"
            or not other["result"].get("outputs")
            or other["dispatch_phase"] not in (None, "completed", "cancelled")
            for other in evidence["other_attempts"]
        ):
            reasons.append("other_attempt_outcome_unconfirmed")
        receipts = [
            r
            for r in evidence["quarantined_results"]
            if r["result"].get("attempt_id") == run["id"]
        ]
        if len(receipts) != 1 or not receipts[0]["verified"]:
            reasons.append("verified_terminal_receipt_required")
        else:
            try:
                for ref in receipts[0]["outputs"].values():
                    self.runtime.store.path(job["owner_id"], ref)
            except (ValueError, OSError):
                reasons.append("quarantine_object_unavailable")
        target = evidence["execution_target"]
        q = evidence["dispatch"]
        if q and (
            not receipts
            or receipts[0]["result"].get("transport") != "s3_subprocess"
            or not any(
                e["worker_id"] == q["worker_id"]
                and e["boot_id"] == q["boot_id"]
                and e["state"] in ("busy", "stopping")
                for e in evidence["worker_events"]
            )
        ):
            reasons.append("bound_remote_receive_evidence_required")
        if target:
            workers = target["workers"] or []
            expected = (
                q
                if q
                else (
                    evidence["worker_events"][-1] if evidence["worker_events"] else None
                )
            )
            if (
                not expected
                or not target["fresh"]
                or target["capacity"] != 1
                or len(workers) != 1
            ):
                reasons.append("fresh_bound_worker_required")
            elif (
                workers[0]["id"] != expected["worker_id"]
                or workers[0]["boot_id"] != expected["boot_id"]
                or not workers[0]["running"]
                or workers[0]["state"] != "ready"
            ):
                reasons.append("bound_worker_not_quiescent")
        elif q or (receipts and receipts[0]["result"].get("transport") != "subprocess"):
            reasons.append("registered_execution_target_required")
        if not DispatchQueue._try_guard_in(db, "encode"):
            reasons.append("sender_still_active")
        return not reasons, reasons

    def late_in(self, db, job, run, command, result):
        case = db.execute(
            "SELECT * FROM job_processing_cases WHERE owner_id=%s AND job_id=%s FOR UPDATE",
            (job["owner_id"], job["id"]),
        ).fetchone()
        if not case:
            return False
        response_sha = content_digest(result)
        if not db.execute(
            "SELECT 1 FROM job_processing_late_results WHERE case_id=%s AND message_sha256=%s",
            (case["id"], response_sha),
        ).fetchone():
            verified = False
            outputs = {}
            error = "terminal_output_unverified"
            if (
                result.get("status") == "completed"
                and result.get("process_exit_code") == 0
            ):
                try:
                    if result.get("transport") == "subprocess":
                        delivery = db.execute(
                            "SELECT status,result FROM agent_deliveries WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                            (job["owner_id"], job["id"], run["id"]),
                        ).fetchone()
                        if (
                            not delivery
                            or delivery["status"] != "completed"
                            or content_digest(delivery["result"]) != response_sha
                        ):
                            raise ValueError("local_receipt_missing")
                    outputs = self.runtime._import_outputs(
                        job["owner_id"], command, result
                    )
                    verified = True
                    error = None
                except (ValueError, KeyError, TypeError, OSError):
                    pass
            db.execute(
                "INSERT INTO job_processing_late_results(case_id,message_sha256,result,verified,outputs,error_code) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    case["id"],
                    response_sha,
                    payload(result),
                    verified,
                    payload(outputs),
                    error,
                ),
            )
        return True

    @staticmethod
    def _status_in(db, job, case, evidence, allowed, reasons):
        return {
            "case": dict(case),
            "original": {
                "job_id": job["id"],
                "ticket_number": job["ticket_number"],
                "raw_status": job["status"],
                "generation": job["generation"],
                "claim_id": job["active_claim_id"],
                "attempt_id": case["node_run_id"],
            },
            "evidence": evidence,
            "can_create_child": allowed,
            "hold_reasons": reasons,
            "child": dict(
                db.execute(
                    "SELECT id,owner_id,ticket_number,parent_id,status,active_claim_id,snapshot FROM jobs WHERE owner_id=%s AND id=%s",
                    (job["owner_id"], case["child_id"]),
                ).fetchone()
            )
            if case["child_id"]
            else None,
            "history": [
                dict(r)
                for r in db.execute(
                    "SELECT d.id,d.plan_id,d.actor_id,d.choice,d.reason,d.evidence_sha256,d.child_id,d.created_at,d.acknowledge_duplicate_risk,d.authority_snapshot,p.context AS plan_context,p.revision AS reviewed_revision FROM job_processing_decisions d JOIN job_processing_plans p ON p.id=d.plan_id WHERE d.case_id=%s ORDER BY d.created_at,d.id",
                    (case["id"],),
                ).fetchall()
            ],
        }

    def status(self, actor, job_id):
        with self.database.connection() as db:
            admin(db, actor)
            job, case, run, evidence = self._locked(db, job_id)
            allowed, reasons = self._eligibility(db, job, case, run, evidence)
            return self._status_in(db, job, case, evidence, allowed, reasons)

    def list(self, actor):
        with self.database.connection() as db:
            admin(db, actor)
            ids = [
                r["id"]
                for r in db.execute(
                    "SELECT j.id FROM jobs j WHERE EXISTS(SELECT 1 FROM job_processing_cases c WHERE c.owner_id=j.owner_id AND c.job_id=j.id) OR EXISTS(SELECT 1 FROM node_runs n LEFT JOIN broker_dispatch_queue q ON q.node_run_id=n.id WHERE n.owner_id=j.owner_id AND n.job_id=j.id AND n.node_type='encode' AND (q.phase='unknown' OR (q.node_run_id IS NULL AND n.status='running' AND (n.lease_expires_at IS NULL OR n.lease_expires_at<now())))) ORDER BY j.created_at,j.id"
                ).fetchall()
            ]
        values = []
        for jid in ids:
            try:
                state = self.status(actor, jid)
            except Conflict as error:
                if str(error) == "processing_confirmation_not_required":
                    continue
                raise
            values.append(
                {
                    "job_id": jid,
                    "ticket_number": state["original"]["ticket_number"],
                    **self.projection(state["case"]),
                }
            )
        return values

    def quarantine_reference(self, actor, job_id, message_sha, port):
        import re

        if not isinstance(message_sha, str) or not re.fullmatch(
            "[a-f0-9]{64}", message_sha
        ):
            raise ValueError("invalid_quarantine_id")
        with self.database.connection() as db:
            admin(db, actor)
            job, case, _, _ = self._locked(db, job_id)
            row = db.execute(
                "SELECT verified,outputs FROM job_processing_late_results WHERE case_id=%s AND message_sha256=%s",
                (case["id"], message_sha),
            ).fetchone()
            if not row or not row["verified"] or port not in row["outputs"]:
                raise Missing("verified_quarantine_output_missing")
            return job["owner_id"], row["outputs"][port]

    def preview(self, actor, job_id):
        with self.database.connection() as db:
            admin(db, actor)
            job, case, run, evidence = self._locked(db, job_id)
            allowed, reasons = self._eligibility(db, job, case, run, evidence)
            context = {
                "policy": "encode-terminal-receipt-v1",
                "evidence": evidence,
                "can_create_child": allowed,
                "hold_reasons": reasons,
            }
            plan = uuid4().hex
            db.execute(
                "INSERT INTO job_processing_plans(id,case_id,actor_id,revision,evidence_sha256,context) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    plan,
                    case["id"],
                    actor,
                    case["revision"],
                    digest(context),
                    payload(context),
                ),
            )
            return {
                **self._status_in(db, job, case, evidence, allowed, reasons),
                "plan_id": plan,
            }

    def decide(
        self,
        actor,
        job_id,
        *,
        plan_id,
        decision_id,
        choice,
        reason,
        acknowledge_duplicate_risk,
    ):
        identity(plan_id)
        identity(decision_id)
        if (
            choice not in ("hold", "create_child")
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1000
            or type(acknowledge_duplicate_risk) is not bool
        ):
            raise ValueError("invalid_processing_decision")
        request = {
            "actor_id": actor,
            "job_id": job_id,
            "plan_id": plan_id,
            "choice": choice,
            "reason": reason,
            "acknowledge_duplicate_risk": acknowledge_duplicate_risk,
        }
        with self.database.connection() as db:
            admin(db, actor)
            authority = {"id": actor, "role": "admin", "active": True}
            job, case, run, evidence = self._locked(db, job_id)
            allowed, reasons = self._eligibility(db, job, case, run, evidence)
            old = db.execute(
                "SELECT * FROM job_processing_decisions WHERE id=%s", (decision_id,)
            ).fetchone()
            if old:
                if old["request_sha256"] != digest(request):
                    raise Conflict("decision_id_reused")
                return self._status_in(db, job, case, evidence, allowed, reasons)
            plan = db.execute(
                "SELECT * FROM job_processing_plans WHERE id=%s AND case_id=%s AND actor_id=%s",
                (plan_id, case["id"], actor),
            ).fetchone()
            context = {
                "policy": "encode-terminal-receipt-v1",
                "evidence": evidence,
                "can_create_child": allowed,
                "hold_reasons": reasons,
            }
            if (
                not plan
                or plan["revision"] != case["revision"]
                or plan["evidence_sha256"] != digest(context)
            ):
                raise Conflict("processing_review_changed")
            if case["child_id"]:
                raise Conflict("child_already_created")
            child = None
            if choice == "create_child":
                if not allowed or acknowledge_duplicate_risk is not True:
                    raise Conflict("verified_terminal_receipt_and_risk_ack_required")
                for ref in job["snapshot"]["inputs"].values():
                    self.runtime.store.path(job["owner_id"], ref)
                snapshot = {
                    **job["snapshot"],
                    "recovery": {
                        "parent_id": job_id,
                        "snapshot_sha256": job["snapshot_sha256"],
                        "review_decision_id": decision_id,
                    },
                }
                child = uuid4().hex
                creation = {
                    "asset_id": job["asset_id"],
                    "definition_id": job["workflow_id"],
                    "definition_revision": job["workflow_revision"],
                    "options": snapshot["options"],
                    "parent_id": job_id,
                }
                db.execute(
                    "INSERT INTO jobs(owner_id,id,asset_id,workflow_id,workflow_revision,status,snapshot,snapshot_sha256,parent_id,creation_request_id,creation_sha256,recovery_ready,workflow_owner_id) VALUES(%s,%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,true,%s)",
                    (
                        job["owner_id"],
                        child,
                        job["asset_id"],
                        job["workflow_id"],
                        job["workflow_revision"],
                        payload(snapshot),
                        content_digest(snapshot),
                        job_id,
                        "processing-review:" + decision_id,
                        content_digest(creation),
                        job["workflow_owner_id"],
                    ),
                )
            db.execute(
                "INSERT INTO job_processing_decisions(id,case_id,plan_id,actor_id,choice,reason,request_sha256,evidence_sha256,owner_id,child_id,acknowledge_duplicate_risk,authority_snapshot) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    decision_id,
                    case["id"],
                    plan_id,
                    actor,
                    choice,
                    reason,
                    digest(request),
                    digest(context),
                    job["owner_id"],
                    child,
                    acknowledge_duplicate_risk,
                    payload(authority),
                ),
            )
            case = db.execute(
                "UPDATE job_processing_cases SET state=%s,child_id=%s,revision=revision+1 WHERE id=%s RETURNING *",
                ("child_created" if child else "held", child, case["id"]),
            ).fetchone()
            if child:
                # Preserve original phase/publish/worker facts; only add the audited release link.
                db.execute(
                    "UPDATE broker_dispatch_queue SET release_decision_id=%s WHERE owner_id=%s AND job_id=%s AND node_run_id=%s AND release_decision_id IS NULL",
                    (decision_id, job["owner_id"], job_id, run["id"]),
                )
            return self._status_in(
                db,
                job,
                case,
                evidence,
                False,
                ["child_already_created"] if child else reasons,
            )
