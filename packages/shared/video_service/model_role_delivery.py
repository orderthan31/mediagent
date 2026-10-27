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

    def recover(self, owner, job_id, task, revision, request_id):
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
                    if old["request_sha256"] != digest(payload):
                        raise Conflict("result_recovery_request_changed")
                    if old["response"] is not None:
                        return old["response"]
                    raise Conflict("result_recovery_pending_inspect")
                row = c.execute(
                    "SELECT d.* FROM model_role_result_deliveries d JOIN model_role_tasks t ON t.task_id=d.task_id WHERE t.owner_id=%s AND t.job_id=%s AND d.task_id=%s FOR UPDATE OF d",
                    (owner, job_id, task),
                ).fetchone()
                if (
                    not row
                    or row["state"] != "held"
                    or row["revision"] != revision
                    or row["attempts"] >= self.limit
                ):
                    raise Conflict("result_recovery_not_available_or_changed")
                c.execute(
                    "INSERT INTO model_role_result_recoveries(owner_id,request_id,task_id,request_sha256)VALUES(%s,%s,%s,%s)",
                    (owner, request_id, task, digest(payload)),
                )
            try:
                self.attempt(row["packet"])
            except RoleResultHeld:
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
