"""Trusted application API/operator connection for explicitly enrolled new jobs."""

import json

from psycopg.types.json import Jsonb

from .cpu_agents import digest
from .model_role_delivery import RoleResultDeliveries
from .model_role_delivery import RoleResultHeld as RoleResultHeld
from .postgres import Conflict
from .postgres.model_roles import ModelRoles
from .rabbitmq_transport import InvalidMessage


class ModelRoleCoordinator:
    def __init__(self, runtime, factory):
        self.runtime = runtime
        self.factory = factory
        self.role_factory = getattr(factory, "model_role_factory", None)
        if self.role_factory is None:
            raise Conflict("independent_role_transport_unavailable")
        self.roles = ModelRoles(
            runtime, result_store=getattr(factory, "model_role_result_store", None)
        )

    def enroll_job(self, owner, job_id, revision, request_id):
        payload = {"job_id": job_id, "revision": revision, "request_id": request_id}
        with self.runtime.database.connection() as c:
            job = self.runtime._job(c, owner, job_id, lock=True)
            prior = c.execute(
                "SELECT * FROM model_role_enrollments WHERE owner_id=%s AND request_id=%s",
                (owner, request_id),
            ).fetchone()
            if prior:
                if prior["request_sha256"] != digest(payload):
                    raise Conflict("role_enrollment_request_changed")
                return prior["response"]
            existing = c.execute(
                "SELECT 1 FROM model_role_enrollments WHERE owner_id=%s AND job_id=%s AND generation=%s",
                (owner, job_id, job["generation"]),
            ).fetchone()
            if existing:
                raise Conflict("role_job_already_enrolled")
            attempts = c.execute(
                "SELECT count(*) n FROM node_runs WHERE owner_id=%s AND job_id=%s",
                (owner, job_id),
            ).fetchone()["n"]
            if (
                job["status"] != "draft"
                or job["cancel_requested"]
                or job["active_claim_id"]
                or attempts
                or job["revision"] != revision
            ):
                raise Conflict("role_enrollment_requires_fresh_draft_revision")
            nodes = [
                n
                for n in job["snapshot"]["definition"]["nodes"]
                if n["type"] == "transcribe"
            ]
            if not nodes or any(
                not n.get("model_ref")
                or n["options"].get("clock_policy") != "packed_projection_v5"
                or n["options"].get("batch_policy") != "bounded_60s_v1"
                or n.get("fallback_refs")
                for n in nodes
            ):
                raise Conflict(
                    "role_enrollment_requires_supported_frozen_transcription"
                )
            response = {
                "enrolled": True,
                "job_id": job_id,
                "generation": job["generation"],
                "revision": revision + 1,
                "role": "transcription",
            }
            c.execute(
                "INSERT INTO model_role_enrollments(owner_id,job_id,generation,snapshot_sha256,request_id,request_sha256,response)VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    job_id,
                    job["generation"],
                    job["snapshot_sha256"],
                    request_id,
                    digest(payload),
                    Jsonb(response),
                ),
            )
            c.execute(
                "UPDATE jobs SET revision=revision+1,updated_at=now()WHERE owner_id=%s AND id=%s",
                (owner, job_id),
            )
            return response

    @staticmethod
    def enrolled(runtime, owner, job_id):
        with runtime.database.connection() as c:
            if not c.execute(
                "SELECT to_regclass('model_role_enrollments') relation"
            ).fetchone()["relation"]:
                return False
            return bool(
                c.execute(
                    "SELECT 1 FROM model_role_enrollments e JOIN jobs j ON j.owner_id=e.owner_id AND j.id=e.job_id WHERE e.owner_id=%s AND e.job_id=%s AND e.generation=j.generation AND e.snapshot_sha256=j.snapshot_sha256",
                    (owner, job_id),
                ).fetchone()
            )

    def publish(self, owner, command):
        self.roles.enroll(owner, command)

        def send(envelope):
            with self.role_factory() as client:
                return client.publish_command(envelope)

        return self.roles.publish_exact(
            owner, command["run_id"], command["attempt_id"], send
        )

    @staticmethod
    def enqueue_cancel_in(c, job):
        if not c.execute(
            "SELECT to_regclass('model_role_controls') relation"
        ).fetchone()["relation"]:
            return
        tasks = c.execute(
            "SELECT task_id,attempt_id,envelope_sha256 FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND phase NOT IN ('accepted','cancelled')",
            (job["owner_id"], job["id"]),
        ).fetchall()
        for task in tasks:
            packet = {
                "version": 1,
                "role": "transcription",
                "task_id": task["task_id"],
                "request_sha256": task["envelope_sha256"],
            }
            c.execute(
                "INSERT INTO model_role_controls(owner_id,job_id,attempt_id,kind,request_id,packet,packet_sha256)VALUES(%s,%s,%s,'cancel',%s,%s,%s)ON CONFLICT DO NOTHING",
                (
                    job["owner_id"],
                    job["id"],
                    task["attempt_id"],
                    "product-cancel:" + str(job["generation"]),
                    Jsonb(packet),
                    digest(packet),
                ),
            )

    def publish_cancels(self, owner, job_id, *, outcome=None):
        # Exact newly admitted controls only. Never reset sending/unknown or scan DLQ.
        with self.runtime.database.connection() as c:
            job = self.runtime._job(c, owner, job_id)
            if not job["cancel_requested"]:
                return {
                    "cancel_applied": False,
                    "status": "terminal_noop",
                    "role_delivery_complete": None,
                    "role_controls": [],
                }
            controls = c.execute(
                "SELECT * FROM model_role_controls WHERE owner_id=%s AND job_id=%s AND kind='cancel'AND phase='ready'ORDER BY created_at",
                (owner, job_id),
            ).fetchall()
        for control in controls:
            with self.runtime.database.connection() as c:
                changed = c.execute(
                    "UPDATE model_role_controls SET phase='sending'WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'AND request_id=%s AND phase='ready'RETURNING packet",
                    (owner, job_id, control["attempt_id"], control["request_id"]),
                ).fetchone()
            if not changed:
                continue
            try:
                with self.role_factory() as client:
                    if client.publish_cancel(changed["packet"]) is not True:
                        raise Conflict("role_cancel_publish_unconfirmed")
            except Exception:
                with self.runtime.database.connection() as c:
                    c.execute(
                        "UPDATE model_role_controls SET phase='unknown'WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'AND request_id=%s AND phase='sending'",
                        (owner, job_id, control["attempt_id"], control["request_id"]),
                    )
            else:
                with self.runtime.database.connection() as c:
                    c.execute(
                        "UPDATE model_role_controls SET phase='sent'WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'AND request_id=%s AND phase='sending'",
                        (owner, job_id, control["attempt_id"], control["request_id"]),
                    )
        with self.runtime.database.connection() as c:
            states = c.execute(
                "SELECT attempt_id,phase FROM model_role_controls WHERE owner_id=%s AND job_id=%s AND kind='cancel'ORDER BY created_at",
                (owner, job_id),
            ).fetchall()
        return {
            "cancel_applied": True,
            "status": outcome or "already_requested",
            "role_delivery_complete": all(v["phase"] == "acknowledged" for v in states),
            "role_controls": states,
        }

    def _cancel_ack(self, packet):
        if (
            type(packet) is not dict
            or set(packet)
            != {"version", "role", "task_id", "request_sha256", "status", "kind"}
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["role"] != "transcription"
            or packet["kind"] != "cancel_ack"
            or packet["status"] not in {"cancelled", "completed"}
        ):
            raise InvalidMessage("invalid_role_cancel_ack")
        with self.runtime.database.connection() as c:
            task = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
            ).fetchone()
            if not task or task["envelope_sha256"] != packet["request_sha256"]:
                raise InvalidMessage("role_cancel_ack_scope_changed")
            job = self.runtime._job(c, task["owner_id"], task["job_id"], lock=True)
            controls = c.execute(
                "SELECT * FROM model_role_controls WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'AND phase IN ('sending','sent','unknown','acknowledged')",
                (task["owner_id"], task["job_id"], task["attempt_id"]),
            ).fetchall()
            if not job["cancel_requested"] or not controls:
                raise InvalidMessage("role_cancel_not_admitted")
            for control in controls:
                if control["ack"] is not None and control["ack"] != packet:
                    raise InvalidMessage("immutable_role_cancel_ack_changed")
                c.execute(
                    "UPDATE model_role_controls SET phase='acknowledged',ack=%s WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'AND request_id=%s",
                    (
                        Jsonb(packet),
                        task["owner_id"],
                        task["job_id"],
                        task["attempt_id"],
                        control["request_id"],
                    ),
                )
            if packet["status"] == "cancelled" and task["phase"] != "accepted":
                ModelRoles.cancelled_in(
                    c, task["owner_id"], task["job_id"], task["attempt_id"]
                )
        return None

    def receive(self, delivery):
        if (
            delivery.message_type
            not in {"mideagent.model.result.v1", "mideagent.model.cancel_ack.v1"}
            or delivery.content_type != "application/json"
            or len(delivery.body) > 65536
        ):
            raise InvalidMessage("invalid_role_result_delivery")

        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError("duplicate_role_result_key")
                value[key] = item
            return value

        def constant(value):
            raise ValueError("nonfinite_role_result")

        try:
            packet = json.loads(
                delivery.body, object_pairs_hook=pairs, parse_constant=constant
            )
        except (ValueError, UnicodeError, RecursionError):
            raise InvalidMessage("invalid_role_result_json") from None
        if type(packet) is not dict or packet.get("task_id") != delivery.message_id:
            raise InvalidMessage("role_result_message_identity_changed")
        if delivery.message_type == "mideagent.model.cancel_ack.v1":
            return self._cancel_ack(packet)
        return RoleResultDeliveries(self).receive(packet)

    def _dispatch_after_result(self, packet):
        with self.runtime.database.connection() as c:
            row = c.execute(
                "SELECT owner_id,job_id,phase FROM model_role_tasks WHERE task_id=%s",
                (packet["task_id"],),
            ).fetchone()
        if row and row["phase"] == "accepted":
            from .rabbitmq_controller import BrokerController

            BrokerController(self.runtime, self.factory).dispatch(
                row["owner_id"], row["job_id"]
            )
        return None

    def recover_result(self, owner, job_id, task, revision, request_id):
        return RoleResultDeliveries(self).recover(
            owner, job_id, task, revision, request_id
        )

    def inspect_shared(self, actor, job_id):
        with self.runtime.database.connection() as c:
            job = self.runtime._shared_job(c, job_id)
        return self.inspect(job["owner_id"], job_id)

    def inspect(self, owner, job_id):
        with self.runtime.database.connection() as c:
            self.runtime._job(c, owner, job_id)
            enrolled = c.execute(
                "SELECT generation FROM model_role_enrollments WHERE owner_id=%s AND job_id=%s",
                (owner, job_id),
            ).fetchall()
            tasks = c.execute(
                "SELECT t.task_id,t.phase,t.held_reason,t.used_calls,t.envelope,(SELECT count(*)FROM model_role_tool_calls h WHERE h.task_id=t.task_id)reserved_calls FROM model_role_tasks t WHERE t.owner_id=%s AND t.job_id=%s ORDER BY t.created_at",
                (owner, job_id),
            ).fetchall()
            result = []
            limit = RoleResultDeliveries(self).limit
            for task in tasks:
                delivery = c.execute(
                    "SELECT * FROM model_role_result_deliveries WHERE task_id=%s",
                    (task["task_id"],),
                ).fetchone()
                cancel = c.execute(
                    "SELECT phase FROM model_role_controls WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND kind='cancel'ORDER BY created_at DESC LIMIT 1",
                    (owner, job_id, task["task_id"]),
                ).fetchone()
                issues = c.execute(
                    "SELECT chunk_index,status,error_code FROM model_role_tool_calls WHERE task_id=%s AND status IN ('unknown','failed')ORDER BY chunk_index",
                    (task["task_id"],),
                ).fetchall()
                delivery_service = RoleResultDeliveries(self)
                active = (
                    delivery_service.owner_active(task["task_id"])
                    if delivery
                    else False
                )
                pending = c.execute(
                    "SELECT r.request_id,v.admitted_revision FROM model_role_result_recoveries r LEFT JOIN model_role_recovery_reservations v ON v.owner_id=r.owner_id AND v.request_id=r.request_id WHERE r.task_id=%s AND r.response IS NULL ORDER BY r.created_at LIMIT 1",
                    (task["task_id"],),
                ).fetchone()
                held = delivery and delivery["state"] in {
                    "held",
                    "receiving",
                    "rejected",
                }
                decision = (
                    delivery_service.durable_decision(c, delivery["packet"])
                    if delivery and delivery["state"] in {"held", "receiving"}
                    else None
                )
                choices = (
                    ["retry_result_delivery"]
                    if delivery
                    and not active
                    and delivery["state"] in {"held", "receiving"}
                    and (delivery["attempts"] < limit or decision is not None)
                    else []
                )
                interrupted = (
                    delivery and delivery["state"] == "receiving" and not active
                )
                display_state = (
                    task["phase"]
                    if task["phase"] in {"cancelled", "accepted"}
                    else (
                        "receiving"
                        if active and held
                        else ("held" if held else task["phase"])
                    )
                )
                reason = (
                    (
                        delivery["error_code"]
                        or ("result_delivery_interrupted" if interrupted else None)
                    )
                    if held
                    else task["held_reason"]
                )
                result.append(
                    {
                        "task_id": task["task_id"],
                        "state": display_state,
                        "reason": reason,
                        "delivery_state": delivery["state"] if delivery else None,
                        "delivery_owner_active": active,
                        "pending_recovery": {
                            "request_id": pending["request_id"],
                            "revision": pending["admitted_revision"],
                        }
                        if pending and pending["admitted_revision"] is not None
                        else None,
                        "reserved_calls": task["reserved_calls"],
                        "reported_model_calls": task["used_calls"],
                        "max_calls": task["envelope"]["task"]["max_calls"],
                        "call_issues": issues,
                        "cancel_delivery": cancel["phase"] if cancel else None,
                        "delivery_revision": delivery["revision"] if delivery else None,
                        "delivery_attempts": delivery["attempts"] if delivery else None,
                        "delivery_attempt_limit": limit,
                        "recovery_choices": choices,
                    }
                )
            return {"enrolled": bool(enrolled), "tasks": result}
