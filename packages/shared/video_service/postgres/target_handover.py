"""Admin admission for host-staged exact one-slot targets. No native authority."""

import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from . import Conflict, Missing
from .control_recovery import admin, digest, identity, public


class TargetHandover:
    def __init__(self, store):
        self.store, self.database = store, store.database

    @staticmethod
    def group_in(db, agent):
        row = db.execute(
            "SELECT *,observed_at>now()-interval '15 seconds' AS fresh FROM remote_control_groups WHERE agent_id=%s FOR UPDATE",
            (agent,),
        ).fetchone()
        if not row:
            raise Missing("control_group_missing")
        return row

    @staticmethod
    def context_in(db, group, *, pending=None):
        if (
            group["capacity"] != 1
            or len(group["slot_ids"]) != 1
            or group["enabled"]
            or group["replicas"] != 0
            or group["pending_request"]
            or group["quarantined"]
            or group["pending_handover"] != pending
            or not group["observed_at"]
        ):
            raise Conflict("handover_requires_stopped_unblocked_slot")
        rows = group["observed"] or []
        if len(rows) != 1:
            raise Conflict("handover_requires_bound_stop")
        row = rows[0]
        if (
            row.get("id") != group["slot_ids"][0]
            or row.get("running") is not False
            or row.get("state") != "stopped"
            or row.get("exit_code") != 0
            or row.get("report_state") != "stopped"
            or not row.get("boot_id")
            or row.get("restart_policy") != "no"
            or not row.get("target_id")
            or not row.get("image_id")
        ):
            raise Conflict("handover_requires_bound_stop")
        requests = db.execute(
            "SELECT * FROM remote_control_requests WHERE agent_id=%s ORDER BY revision",
            (group["agent_id"],),
        ).fetchall()
        actions = db.execute(
            "SELECT a.* FROM remote_control_actions a JOIN remote_control_requests r ON r.request_id=a.request_id WHERE r.agent_id=%s ORDER BY a.id",
            (group["agent_id"],),
        ).fetchall()
        if any(r["phase"] != "succeeded" for r in requests) or any(
            a["phase"] != "confirmed" for a in actions
        ):
            raise Conflict("handover_unresolved_control")
        if db.execute(
            "SELECT 1 FROM broker_dispatch_queue WHERE agent_id=%s AND phase IN ('sending','sent','received','unknown') AND release_decision_id IS NULL",
            (group["agent_id"],),
        ).fetchone():
            raise Conflict("handover_unresolved_dispatch")
        stopped = [
            a
            for a in actions
            if a["action"] == "stop"
            and a["before_boot_id"] == row["boot_id"]
            and a["issue_count"] == 1
        ]
        if not stopped:
            raise Conflict("handover_requires_signed_stop")
        action = max(stopped, key=lambda a: a["issued_at"])
        batch = db.execute(
            "SELECT * FROM remote_control_batches WHERE request_id=%s",
            (action["request_id"],),
        ).fetchone()
        ack = db.execute(
            "SELECT receipt_sha256,facts,valid FROM remote_control_ack_evidence WHERE action_id=%s",
            (action["id"],),
        ).fetchone()
        if (
            not batch
            or batch["contract_sha256"] != group["contract_sha256"]
            or not ack
            or not ack["valid"]
            or ack["facts"].get("target_id") != row["target_id"]
            or ack["facts"].get("image_id") != row["image_id"]
            or ack["facts"].get("after_started_at") != row["started_at"]
        ):
            raise Conflict("handover_requires_signed_stop")
        value = {
            "agent": group["agent_id"],
            "epoch": group["target_epoch"],
            "contract": group["contract_sha256"],
            "revision": group["revision"] - (1 if pending else 0),
            "observation_revision": group["observation_revision"],
            "observation": row,
            "requests": [dict(r) for r in requests],
            "actions": [dict(a) for a in actions],
            "stop_action": dict(action),
            "ack": dict(ack),
            "baseline": dict(batch),
        }
        return json.loads(json.dumps(value, default=public))

    def status(self, actor, agent):
        with self.database.connection() as db:
            admin(db, actor)
            group = self.group_in(db, agent)
            candidates = db.execute(
                "SELECT * FROM control_target_candidates WHERE agent_id=%s ORDER BY created_at",
                (agent,),
            ).fetchall()
            history = db.execute(
                "SELECT * FROM control_target_transitions WHERE agent_id=%s ORDER BY created_at",
                (agent,),
            ).fetchall()
            return {
                "agent_id": agent,
                "epoch": group["target_epoch"],
                "revision": group["revision"],
                "pending": group["pending_handover"],
                "candidates": [dict(r) for r in candidates],
                "history": [dict(r) for r in history],
                "automatic_start": False,
            }

    def preview(self, actor, agent, candidate_id):
        identity(candidate_id)
        with self.database.connection() as db:
            admin(db, actor)
            group = self.group_in(db, agent)
            candidate = db.execute(
                "SELECT * FROM control_target_candidates WHERE id=%s AND agent_id=%s",
                (candidate_id, agent),
            ).fetchone()
            if not candidate:
                raise Missing("handover_candidate_missing")
            context = self.context_in(db, group)
            if digest(context) != candidate["context_sha256"]:
                raise Conflict("handover_evidence_changed")
            plan_id = uuid4().hex
            db.execute(
                "INSERT INTO control_target_plans(id,agent_id,candidate_id,actor_id,context,context_sha256) VALUES(%s,%s,%s,%s,%s,%s)",
                (plan_id, agent, candidate_id, actor, Jsonb(context), digest(context)),
            )
            return {
                "id": plan_id,
                "candidate_id": candidate_id,
                "revision": group["revision"],
                "old": candidate["old_descriptor"],
                "new": candidate["new_descriptor"],
                "from_epoch": candidate["from_epoch"],
                "automatic_start": False,
            }

    def submit(self, actor, agent, *, plan_id, decision_id, reason, acknowledge):
        identity(plan_id)
        identity(decision_id)
        if (
            not isinstance(reason, str)
            or not 10 <= len(reason.strip()) <= 1000
            or acknowledge is not True
        ):
            raise ValueError("handover_reason_and_acknowledgement_required")
        reason = reason.strip()
        with self.database.connection() as db:
            admin(db, actor)
            group = self.group_in(db, agent)
            prior = db.execute(
                "SELECT * FROM control_target_transitions WHERE id=%s", (decision_id,)
            ).fetchone()
            if prior:
                if any(
                    prior[k] != v
                    for k, v in {
                        "actor_id": actor,
                        "agent_id": agent,
                        "plan_id": plan_id,
                        "reason": reason,
                    }.items()
                ):
                    raise Conflict("handover_decision_id_reused")
                return dict(prior)
            if group["pending_handover"]:
                raise Conflict("handover_in_progress")
            plan = db.execute(
                "SELECT * FROM control_target_plans WHERE id=%s AND agent_id=%s AND actor_id=%s",
                (plan_id, agent, actor),
            ).fetchone()
            if not plan:
                raise Missing("handover_plan_missing")
            if digest(self.context_in(db, group)) != plan["context_sha256"]:
                raise Conflict("handover_evidence_changed")
            row = db.execute(
                "INSERT INTO control_target_transitions(id,agent_id,candidate_id,plan_id,actor_id,authority,reason,phase) VALUES(%s,%s,%s,%s,%s,%s,%s,'planned') RETURNING *",
                (
                    decision_id,
                    agent,
                    plan["candidate_id"],
                    plan_id,
                    actor,
                    Jsonb({"id": actor, "role": "admin", "active": True}),
                    reason,
                ),
            ).fetchone()
            db.execute(
                "UPDATE remote_control_groups SET pending_handover=%s,revision=revision+1 WHERE agent_id=%s",
                (decision_id, agent),
            )
            return dict(row)
