"""Application-owned mapping and adoption, never a model executor.

Only explicit newly enrolled attempts are addressed. No pending-job/outbox scan,
model inference, automatic unknown retry, credential sharing or worker DB access.
"""

import json
from copy import deepcopy

from psycopg.types.json import Jsonb

from ..cpu_agents import canonical, digest
from ..packed_projection import project, validate_projection_clock
from . import Conflict, Missing


class ModelRoles:
    def __init__(self, runtime, *, result_store=None):
        self.runtime = runtime
        self.results = result_store or runtime.store

    def _current(self, c, owner, command):
        runtime = self.runtime
        job = runtime._job(c, owner, command["run_id"], lock=True)
        run = c.execute(
            "SELECT *,lease_expires_at>now() lease_valid FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s FOR UPDATE",
            (owner, command["run_id"], command["attempt_id"]),
        ).fetchone()
        if (
            not run
            or run["request_sha256"] != digest(command)
            or run["request"] != command
        ):
            raise Conflict("model_role_request_changed")
        if (
            job["cancel_requested"]
            or job["generation"] != command["generation"]
            or run["generation"] != command["generation"]
            or job["active_claim_id"] != run["claim_id"]
            or run["status"] != "running"
            or not run["lease_valid"]
        ):
            raise Conflict("model_role_attempt_not_active")
        return job, run

    def enroll(self, owner, command):
        command = deepcopy(command)
        runtime = self.runtime
        config = command.get("transcription", {})
        if (
            command.get("agent", {}).get("id") != "transcribe"
            or config.get("clock_policy") != "packed_projection_v5"
            or config.get("batch_policy") != "bounded_60s_v1"
        ):
            raise Conflict("independent_role_requires_explicit_packed_batched_contract")
        pins = config["candidates"]
        # Never silently drop configured fallbacks while that contract is pending.
        if len(pins) != 1:
            raise Conflict("independent_role_candidate_chain_not_connected")
        cap = config["max_model_calls"]
        if type(cap) is not int or cap < 1:
            raise Conflict("invalid_role_frozen_call_budget")
        runtime._preflight_cpu_inputs(owner, command["run_id"], command)
        from ..long_audio_budget import read_clock

        clock = read_clock(
            json.loads(runtime.store.read(owner, command["inputs"]["timeline"])),
            audio_sha256=command["inputs"]["audio"]["sha256"],
        )
        validate_projection_clock(clock, policy="packed_projection_v5")
        audio = command["inputs"]["audio"]
        envelope = {
            "version": 1,
            "role": "transcription",
            "task": {
                "version": 1,
                "task_id": command["attempt_id"],
                "role": "transcription",
                "audio": {k: audio[k] for k in ["sha256", "bytes"]},
                "model": {k: pins[0][k] for k in ["model_id", "revision"]},
                "source_language": config["source_language"],
                "chunk_frames": 960000,
                "max_calls": cap,
                "timeline": clock,
            },
            "source": {"owner": owner, "reference": audio},
            "output_owner": owner,
        }
        with runtime.database.connection() as c:
            self._current(c, owner, command)
            previous = c.execute(
                "SELECT * FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND attempt_id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            if previous:
                if previous["envelope"] != envelope or previous[
                    "request_sha256"
                ] != digest(command):
                    raise Conflict("immutable_role_mapping_changed")
                return previous["envelope"]
            outbox = c.execute(
                "SELECT published_at,payload FROM message_outbox WHERE owner_id=%s AND aggregate_id=%s AND id=%s FOR UPDATE",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            delivered = c.execute(
                "SELECT 1 FROM agent_deliveries WHERE owner_id=%s AND job_id=%s AND node_run_id=%s",
                (owner, command["run_id"], command["attempt_id"]),
            ).fetchone()
            if (
                not outbox
                or outbox["published_at"]
                or outbox["payload"] != command
                or delivered
            ):
                raise Conflict("historical_or_started_attempt_not_enrolled")
            c.execute(
                "INSERT INTO model_role_tasks(owner_id,job_id,attempt_id,task_id,generation,request_sha256,envelope,envelope_sha256,frozen_candidates)VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    command["run_id"],
                    command["attempt_id"],
                    command["attempt_id"],
                    command["generation"],
                    digest(command),
                    Jsonb(envelope),
                    digest(envelope),
                    Jsonb(pins),
                ),
            )
        return envelope

    def publish_exact(self, owner, job_id, attempt_id, send_confirm):
        # A session advisory guard spans both durable commits and external I/O.
        # A lost send/commit is never automatically promoted to ready.
        with self.runtime.database.connection() as c:
            guard = "model-role:" + owner + ":" + attempt_id
            locked = c.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok", (guard,)
            ).fetchone()["ok"]
            if not locked:
                raise Conflict("model_role_sender_busy")
            c.commit()
            try:
                row = c.execute(
                    "SELECT * FROM model_role_tasks WHERE owner_id=%s AND job_id=%s AND attempt_id=%s FOR UPDATE",
                    (owner, job_id, attempt_id),
                ).fetchone()
                if not row:
                    raise Missing("model_role_mapping_missing")
                if row["phase"] != "ready":
                    return False
                run = c.execute(
                    "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                    (owner, job_id, attempt_id),
                ).fetchone()
                self._current(c, owner, run["request"])
                c.execute(
                    "UPDATE model_role_tasks SET phase='sending'WHERE task_id=%s",
                    (row["task_id"],),
                )
                c.commit()
                # A received command may execute from the already durable sending
                # grant before confirm returns. Release row locks before network I/O;
                # the bridge independently fences each call against product cancel.
                self._current(c, owner, run["request"])
                c.commit()
                if send_confirm(deepcopy(row["envelope"])) is not True:
                    raise Conflict("model_role_publish_unconfirmed")
                c.execute(
                    "UPDATE model_role_tasks SET phase='sent'WHERE task_id=%s AND phase='sending'",
                    (row["task_id"],),
                )
                c.execute(
                    "UPDATE message_outbox SET published_at=now()WHERE id=%s",
                    (attempt_id,),
                )
                c.commit()
                return True
            except Exception:
                c.rollback()
                c.execute(
                    "UPDATE model_role_tasks SET phase='unknown',held_reason='command_publication_unknown'WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND phase='sending'",
                    (owner, job_id, attempt_id),
                )
                c.commit()
                raise
            finally:
                c.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (guard,))
                c.commit()

    def receive(self, message):
        if (
            type(message) is not dict
            or set(message)
            != {
                "version",
                "role",
                "task_id",
                "request_sha256",
                "status",
                "output_owner",
                "result_ref",
            }
            or type(message["version"]) is not int
            or message["version"] != 1
            or message["role"] != "transcription"
        ):
            raise Conflict("invalid_role_result_envelope")
        with self.runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (message["task_id"],)
            ).fetchone()
            if not row:
                raise Missing("role_result_mapping_missing")
            if (
                message["request_sha256"] != row["envelope_sha256"]
                or message["output_owner"] != row["owner_id"]
            ):
                raise Conflict("role_result_scope_changed")
            if row["result_sha256"] and row["result_sha256"] != digest(message):
                raise Conflict("immutable_role_result_changed")
            command = c.execute(
                "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (row["owner_id"], row["job_id"], row["attempt_id"]),
            ).fetchone()["request"]
        owner = row["owner_id"]
        packet = json.loads(
            self.results.read(owner, message["result_ref"], limit=16 * 1024 * 1024)
        )
        envelope = row["envelope"]
        if (
            packet.get("request_sha256") != row["envelope_sha256"]
            or packet.get("task") != envelope["task"]
            or packet.get("source") != envelope["source"]
            or packet.get("role") != "transcription"
        ):
            raise Conflict("role_result_artifact_changed")
        result = packet["result"]
        calls = result.get("model_calls")
        if (
            result.get("task_id") != row["task_id"]
            or result.get("role") != "transcription"
            or result.get("status") != message["status"]
            or type(calls) is not int
            or not 0 <= calls <= envelope["task"]["max_calls"]
        ):
            raise Conflict("invalid_role_result_budget_or_identity")
        if result["status"] != "completed":
            with self.runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_tasks SET phase='held',held_reason=%s,used_calls=%s,result_message=%s,result_sha256=%s WHERE task_id=%s",
                    (
                        result.get("held_reason", result["status"]),
                        calls,
                        Jsonb(message),
                        digest(message),
                        row["task_id"],
                    ),
                )
            return self.runtime.get(owner, row["job_id"])
        if row["adoption_result"] is None:
            trace = result["projection_trace"]
            packed = [r["packed_segment"] for r in trace["rows"]]
            projected, expected = project(
                packed, envelope["task"]["timeline"], policy="packed_projection_v5"
            )
            if expected != trace or projected != result["segments"]:
                raise Conflict("role_projection_trace_changed")
            outputs = {}
            outputs["transcript"] = self.runtime.store.put(
                owner, [canonical(projected)], "transcript"
            )
            packed_ref = self.runtime.store.put(
                owner, [canonical(packed)], "transcript"
            )
            trace = {
                **trace,
                "packed_transcript": packed_ref,
                "audio_sha256": command["inputs"]["audio"]["sha256"],
                "timeline_sha256": command["inputs"]["timeline"]["sha256"],
            }
            outputs["trace"] = self.runtime.store.put(
                owner, [canonical(trace)], "metadata"
            )
            adoption = {
                **{
                    k: command[k]
                    for k in [
                        "protocol_version",
                        "run_id",
                        "attempt_id",
                        "generation",
                        "agent",
                    ]
                },
                "request_sha256": row["request_sha256"],
                "status": "completed",
                "outputs": outputs,
                "transport": "independent_model_role",
                "transcription": {
                    "role_task_id": row["task_id"],
                    "model_calls": calls,
                    "completed_chunks": result["completed_chunks"],
                    "model": envelope["task"]["model"],
                    "tool_mode": packet["tool_mode"],
                    "result_ref": message["result_ref"],
                },
            }
            with self.runtime.database.connection() as c:
                existing = c.execute(
                    "SELECT adoption_result,result_sha256 FROM model_role_tasks WHERE task_id=%s FOR UPDATE",
                    (row["task_id"],),
                ).fetchone()
                if existing["result_sha256"] and existing["result_sha256"] != digest(
                    message
                ):
                    raise Conflict("immutable_role_result_changed")
                if existing["adoption_result"] is not None:
                    adoption = existing["adoption_result"]
                else:
                    c.execute(
                        "UPDATE model_role_tasks SET phase='adopting',used_calls=%s,result_message=%s,result_sha256=%s,adoption_result=%s WHERE task_id=%s",
                        (
                            calls,
                            Jsonb(message),
                            digest(message),
                            Jsonb(adoption),
                            row["task_id"],
                        ),
                    )
        else:
            adoption = row["adoption_result"]
        state = self.runtime.accept(owner, command, adoption)
        accepted = any(
            r["id"] == row["attempt_id"] and r["status"] == "completed"
            for r in state["runs"]
        )
        with self.runtime.database.connection() as c:
            c.execute(
                "UPDATE model_role_tasks SET phase=%s WHERE task_id=%s",
                ("accepted" if accepted else "held", row["task_id"]),
            )
        return state

    def dispatch_next(self, owner, job_id):
        # Only the application orchestrator chooses and reserves the next node.
        return self.runtime.claim_next(owner, job_id)
