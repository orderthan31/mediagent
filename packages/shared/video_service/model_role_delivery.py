"""Explicit artifact/adoption recovery only. No model/worker execution entrypoint."""

from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb

from .cpu_agents import digest
from .object_store import ObjectIntegrityError, ObjectStoreError, validate_reference
from .postgres import Conflict
from .rabbitmq_transport import InvalidMessage


class RoleResultHeld(RuntimeError):
    pass


class RoleResultDeliveries:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.runtime = coordinator.runtime
        self.limit = getattr(coordinator.factory, "model_role_result_attempt_limit", 3)
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("positive_role_result_attempt_limit_required")

    @contextmanager
    def guard(self, task):
        with self.runtime.database.connection() as c:
            key = "role-result-delivery:" + task
            if not c.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok", (key,)
            ).fetchone()["ok"]:
                raise RoleResultHeld("result_delivery_busy")
            c.commit()
            try:
                yield
            finally:
                c.rollback()
                c.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
                c.commit()

    def validate_scope(self, c, packet):
        keys = {
            "version",
            "role",
            "task_id",
            "request_sha256",
            "status",
            "output_owner",
            "result_ref",
        }
        if (
            type(packet) is not dict
            or set(packet) != keys
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["role"] != "transcription"
            or packet["status"] not in {"completed", "held", "cancelled"}
        ):
            raise InvalidMessage("invalid_role_result_envelope")
        try:
            validate_reference(packet["result_ref"])
        except (ValueError, TypeError, KeyError):
            raise InvalidMessage("invalid_role_result_reference") from None
        row = c.execute(
            "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
        ).fetchone()
        if (
            not row
            or row["envelope_sha256"] != packet["request_sha256"]
            or row["owner_id"] != packet["output_owner"]
        ):
            raise InvalidMessage("role_result_scope_changed")
        return row

    def receive(self, packet):
        with self.runtime.database.connection() as c:
            self.validate_scope(c, packet)
        with self.guard(packet["task_id"]):
            with self.runtime.database.connection() as c:
                row = c.execute(
                    "SELECT * FROM model_role_result_deliveries WHERE task_id=%s FOR UPDATE",
                    (packet["task_id"],),
                ).fetchone()
                if row:
                    if row["packet_sha256"] != digest(packet):
                        raise InvalidMessage("immutable_role_result_delivery_changed")
                    if row["state"] == "settled":
                        # Adoption already committed; exact next-node dispatch is idempotent.
                        settled = True
                    elif row["state"] in {"receiving", "held", "rejected"}:
                        raise RoleResultHeld(
                            "result_delivery_requires_explicit_recovery"
                        )
                    else:
                        settled = False
                else:
                    c.execute(
                        "INSERT INTO model_role_result_deliveries(task_id,packet,packet_sha256)VALUES(%s,%s,%s)",
                        (packet["task_id"], Jsonb(packet), digest(packet)),
                    )
                    settled = False
            if settled:
                return self.coordinator._dispatch_after_result(packet)
            self.attempt(packet)
        return None

    def attempt(self, packet):
        task = packet["task_id"]
        with self.runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_result_deliveries WHERE task_id=%s FOR UPDATE",
                (task,),
            ).fetchone()
            if row["attempts"] >= self.limit:
                raise RoleResultHeld("result_delivery_budget_exhausted")
            c.execute(
                "UPDATE model_role_result_deliveries SET state='receiving',attempts=attempts+1,revision=revision+1,error_code=NULL WHERE task_id=%s",
                (task,),
            )
        try:
            self.coordinator.roles.receive(packet)
            self.coordinator._dispatch_after_result(packet)
        except ObjectIntegrityError:
            self.hold(task, "result_artifact_integrity", "rejected")
            raise InvalidMessage("result_artifact_integrity") from None
        except (ObjectStoreError, OSError):
            self.hold(task, "result_transport_unavailable")
            raise RoleResultHeld("result_transport_unavailable") from None
        except psycopg.Error:
            self.hold(task, "result_adoption_commit_unknown")
            raise RoleResultHeld("result_adoption_commit_unknown") from None
        except Exception:
            self.hold(task, "result_adoption_or_dispatch_held")
            raise RoleResultHeld("result_adoption_or_dispatch_held") from None
        else:
            with self.runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_result_deliveries SET state='settled',revision=revision+1,error_code=NULL WHERE task_id=%s",
                    (task,),
                )

    def hold(self, task, reason, state="held"):
        with self.runtime.database.connection() as c:
            c.execute(
                "UPDATE model_role_result_deliveries SET state=%s,revision=revision+1,error_code=%s WHERE task_id=%s",
                (state, reason, task),
            )

    def owner_active(self, task):
        # Observational only. A false result is a hint; explicit recovery must still
        # acquire the very same session guard before inspecting/changing anything.
        with self.runtime.database.connection() as c:
            key = "role-result-delivery:" + task
            acquired = c.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok", (key,)
            ).fetchone()["ok"]
            if acquired:
                c.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
            return not acquired

    def durable_decision(self, c, packet):
        task = self.validate_scope(c, packet)
        if task["result_sha256"] != digest(packet) or task["result_message"] != packet:
            return None
        if packet["status"] != "completed":
            return task["phase"] if task["phase"] in {"held", "cancelled"} else None
        adoption = task["adoption_result"]
        if adoption is None:
            return None
        inbox = c.execute(
            "SELECT payload_sha256 FROM message_inbox WHERE consumer=%s AND message_id=%s",
            ("result:" + task["owner_id"], task["attempt_id"]),
        ).fetchone()
        run = c.execute(
            "SELECT request_sha256,status FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
            (task["owner_id"], task["job_id"], task["attempt_id"]),
        ).fetchone()
        if (
            not inbox
            or inbox["payload_sha256"] != digest(adoption)
            or not run
            or run["request_sha256"] != task["request_sha256"]
        ):
            return None
        if task["phase"] == "cancelled":
            return "cancelled"
        if run["status"] == "completed":
            return "accepted"
        if run["status"] in {"quarantined", "failed", "cancelled"}:
            return "held"
        return None

    def reconcile_adoption(self, packet):
        # Only the explicit caller holding guard() enters here. SQL inbox evidence
        # can settle an already-adopted receipt without GET or another attempt.
        with self.runtime.database.connection() as c:
            decision = self.durable_decision(c, packet)
            if decision is None:
                return False
            c.execute(
                "UPDATE model_role_tasks SET phase=CASE WHEN phase IN ('cancelled','accepted') THEN phase ELSE %s END WHERE task_id=%s",
                (decision, packet["task_id"]),
            )
        try:
            self.coordinator._dispatch_after_result(packet)
        except Exception:
            self.hold(packet["task_id"], "result_dispatch_reconcile_held")
        else:
            with self.runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_result_deliveries SET state='settled',revision=revision+1,error_code=NULL WHERE task_id=%s AND state!='settled'",
                    (packet["task_id"],),
                )
        return True

    @staticmethod
    def response_ready(row, reservation):
        if (
            not row
            or not reservation
            or reservation.get("admitted_revision") is None
            or reservation.get("attempt_before") is None
            or reservation.get("task_id") != row["task_id"]
            or reservation.get("packet_sha256") != row["packet_sha256"]
            or row["attempts"] < reservation["attempt_before"]
        ):
            return False
        return row["state"] == "settled" or (
            row["state"] in {"held", "rejected"}
            and row["attempts"] > reservation["attempt_before"]
        )

    def recover(
        self,
        owner,
        job_id,
        task,
        revision,
        request_id,
        *,
        operation="retry_result_delivery",
    ):
        if operation not in {"retry_result_delivery", "settle_recovery_response"}:
            raise Conflict("invalid_result_recovery_operation")
        payload = {
            "job_id": job_id,
            "task_id": task,
            "revision": revision,
            "request_id": request_id,
        }
        with self.guard(task):
            with self.runtime.database.connection() as c:
                self.runtime._job(c, owner, job_id, lock=True)
                old = c.execute(
                    "SELECT * FROM model_role_result_recoveries WHERE owner_id=%s AND request_id=%s",
                    (owner, request_id),
                ).fetchone()
                if old:
                    if (
                        old["request_sha256"] != digest(payload)
                        or old["task_id"] != task
                    ):
                        raise Conflict("result_recovery_request_changed")
                    if old["response"] is not None:
                        return old["response"]
                row = c.execute(
                    "SELECT d.* FROM model_role_result_deliveries d JOIN model_role_tasks t ON t.task_id=d.task_id WHERE t.owner_id=%s AND t.job_id=%s AND d.task_id=%s FOR UPDATE OF d",
                    (owner, job_id, task),
                ).fetchone()
                if not row:
                    raise Conflict("result_recovery_not_available_or_changed")
                self.validate_scope(c, row["packet"])
                decision = self.durable_decision(c, row["packet"])
                reservation = (
                    c.execute(
                        "SELECT * FROM model_role_recovery_reservations WHERE owner_id=%s AND request_id=%s",
                        (owner, request_id),
                    ).fetchone()
                    if old
                    else None
                )
                if operation == "settle_recovery_response" and (
                    not old or not self.response_ready(row, reservation)
                ):
                    raise Conflict(
                        "pending_recovery_response_not_ready_or_identity_unavailable"
                    )
                if old and reservation:
                    if (
                        reservation["task_id"] != task
                        or reservation["packet_sha256"] != row["packet_sha256"]
                        or reservation["admitted_revision"] != revision
                        or row["attempts"] < reservation["attempt_before"]
                    ):
                        raise Conflict("result_recovery_admission_changed")
                else:
                    # Legacy pending admission may acquire facts only if its exact
                    # original receipt/revision is still unchanged, never by guessing.
                    if (
                        row["state"] not in {"held", "receiving"}
                        or row["revision"] != revision
                    ):
                        raise Conflict("result_recovery_not_available_or_changed")
                    if row["attempts"] >= self.limit and decision is None:
                        raise Conflict("result_recovery_budget_exhausted")
                    other = c.execute(
                        "SELECT request_id FROM model_role_result_recoveries WHERE task_id=%s AND response IS NULL AND NOT(owner_id=%s AND request_id=%s)",
                        (task, owner, request_id),
                    ).fetchone()
                    if other:
                        raise Conflict(
                            "result_recovery_pending_request_must_be_resumed"
                        )
                    if not old:
                        c.execute(
                            "INSERT INTO model_role_result_recoveries(owner_id,request_id,task_id,request_sha256)VALUES(%s,%s,%s,%s)",
                            (owner, request_id, task, digest(payload)),
                        )
                    c.execute(
                        "INSERT INTO model_role_recovery_reservations(owner_id,request_id,task_id,packet_sha256,admitted_revision,attempt_before)VALUES(%s,%s,%s,%s,%s,%s)",
                        (
                            owner,
                            request_id,
                            task,
                            row["packet_sha256"],
                            revision,
                            row["attempts"],
                        ),
                    )
                    reservation = {"attempt_before": row["attempts"]}
            # Pending request response is saved from already-durable progress first.
            # A known failed attempt is finalized, not retried under the same nonce.
            already_attempted = (
                old
                and row["state"] in {"held", "rejected"}
                and row["attempts"] > reservation["attempt_before"]
            )
            if (
                operation != "settle_recovery_response"
                and row["state"] != "settled"
                and not already_attempted
            ):
                if not self.reconcile_adoption(row["packet"]):
                    if row["attempts"] >= self.limit:
                        self.hold(task, "result_delivery_budget_exhausted")
                    else:
                        try:
                            self.attempt(row["packet"])
                        except (RoleResultHeld, InvalidMessage):
                            pass
            with self.runtime.database.connection() as c:
                current = c.execute(
                    "SELECT state,revision,error_code FROM model_role_result_deliveries WHERE task_id=%s",
                    (task,),
                ).fetchone()
                response = {"task_id": task, **current, "model_reexecuted": False}
                c.execute(
                    "UPDATE model_role_result_recoveries SET response=%s WHERE owner_id=%s AND request_id=%s",
                    (Jsonb(response), owner, request_id),
                )
            return response
