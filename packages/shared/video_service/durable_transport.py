"""Injected delivery adapter. No broker library, connection, topology or queue scan.

Callers choose an exact owner/job/message. A publisher must return True only after
its real publisher-confirm; result ack is strictly after the durable DB commit.
"""

from .cpu_agents import canonical
from .postgres import Conflict, Missing


class DurableTransport:
    def __init__(self, runtime):
        self.runtime = runtime

    def publish_exact(self, owner, job_id, message_id, send_confirm):
        with self.runtime.database.connection() as db:
            job = self.runtime._job(db, owner, job_id, lock=True)
            row = db.execute(
                "SELECT * FROM message_outbox WHERE owner_id=%s AND aggregate_id=%s AND id=%s FOR UPDATE",
                (owner, job_id, message_id),
            ).fetchone()
            if not row:
                raise Missing("보낼 메시지를 찾을 수 없습니다.")
            if row["published_at"]:
                return False
            from .postgres.dispatch_queue import DispatchQueue
            queued = DispatchQueue(self.runtime).publish_in(db, job, row, send_confirm)
            if queued is not None:
                return queued
            if row["message_type"] in {"agent.command.v1", "agent.engine.command.v2"}:
                run = db.execute(
                    "SELECT *,lease_expires_at>now() AS lease_valid FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                    (owner, job_id, message_id),
                ).fetchone()
                if (
                    not run
                    or run["status"] != "running"
                    or not run["lease_valid"]
                    or job["cancel_requested"]
                    or run["generation"] != job["generation"]
                ):
                    raise Conflict("취소/이전 세대 명령은 새로 전달하지 않습니다.")
                from .cpu_agents import digest

                if run["request_sha256"] != digest(row["payload"]):
                    raise Conflict("outbox 요청 무결성 오류")
                if row["message_type"] == "agent.engine.command.v2":
                    from .postgres.engine_runtimes import EngineRuntimes

                    try:
                        pin = job["snapshot"]["engine_bindings"][run["node_id"]]
                        current = EngineRuntimes.resolve_in(
                            db, run["node_type"], sha256=pin["sha256"], lock=True
                        )
                        if (
                            current["revision"] != pin["revision"]
                            or row["payload"]["runtime"] != pin["descriptor"]
                            or row["payload"]["agent"]["revision"] != pin["sha256"]
                        ):
                            raise ValueError("engine_revision_changed")
                    except (ValueError, KeyError, TypeError):
                        raise Conflict("발행 직전 engine pin/가용성 변경") from None
            if (
                send_confirm(row["id"], row["message_type"], canonical(row["payload"]))
                is not True
            ):
                raise Conflict(
                    "전달 확인이 없습니다. 메시지는 미발행 상태로 보존했습니다."
                )
            # A crash after confirm but before this commit can redeliver. Attempt
            # inbox/result fencing, not broker exactly-once, handles that boundary.
            db.execute(
                "UPDATE message_outbox SET published_at=now() WHERE id=%s",
                (message_id,),
            )
            return True

    def consume_result(self, owner, command, result, ack):
        state = self.runtime.accept(owner, command, result)
        # accept() has exited its transaction before ack is invoked.
        ack()
        return state

    def consume_command(self, owner, command, publish_result_confirm, ack):
        result = self.runtime.execute_command(owner, command)
        # execute_command persists its attempt receipt, including unknown/failure,
        # before requesting confirmed result delivery. No implicit replay on error.
        if publish_result_confirm(command["attempt_id"], canonical(result)) is not True:
            raise Conflict("결과 전달 확인이 없습니다. receipt를 보존했습니다.")
        ack()
        return result
