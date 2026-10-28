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
    def __init__(self, runtime, *, result_store=None, result_stores=None):
        self.runtime = runtime
        self.results = result_store or runtime.store
        self.result_stores = result_stores or {}

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
        if command.get("translation"):
            envelope, pins = self._translation_envelope(owner, command)
        else:
            config = command.get("transcription", {})
            if (
                command.get("agent", {}).get("id") != "transcribe"
                or config.get("clock_policy") != "packed_projection_v5"
                or config.get("batch_policy") != "bounded_60s_v1"
            ):
                raise Conflict(
                    "independent_role_requires_explicit_packed_batched_contract"
                )
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
            or message["role"] not in {"transcription", "translation"}
        ):
            raise Conflict("invalid_role_result_envelope")
        with self.runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (message["task_id"],)
            ).fetchone()
            if not row:
                raise Missing("role_result_mapping_missing")
            if (
                message["role"] != row["envelope"]["role"]
                or message["request_sha256"] != row["envelope_sha256"]
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
            self.result_stores.get(row["envelope"]["role"], self.results).read(
                owner, message["result_ref"], limit=16 * 1024 * 1024
            )
        )
        envelope = row["envelope"]
        if (
            packet.get("request_sha256") != row["envelope_sha256"]
            or packet.get("task") != envelope["task"]
            or packet.get("source") != envelope["source"]
            or packet.get("role") != envelope["role"]
        ):
            raise Conflict("role_result_artifact_changed")
        result = packet["result"]
        calls = result.get("model_calls")
        if (
            result.get("task_id") != row["task_id"]
            or result.get("role") != envelope["role"]
            or result.get("status") != message["status"]
            or type(calls) is not int
            or not 0 <= calls <= envelope["task"]["max_calls"]
        ):
            raise Conflict("invalid_role_result_budget_or_identity")
        if result["status"] != "completed":
            with self.runtime.database.connection() as c:
                job = self.runtime._job(c, owner, row["job_id"], lock=True)
                current = c.execute(
                    "SELECT phase,result_sha256 FROM model_role_tasks WHERE task_id=%s FOR UPDATE",
                    (row["task_id"],),
                ).fetchone()
                if current["result_sha256"] and current["result_sha256"] != digest(
                    message
                ):
                    raise Conflict("immutable_role_result_changed")
                phase = (
                    current["phase"]
                    if current["phase"] in {"accepted", "cancelled"}
                    else (
                        "cancelled"
                        if result["status"] == "cancelled" and job["cancel_requested"]
                        else "held"
                    )
                )
                c.execute(
                    "UPDATE model_role_tasks SET phase=%s,held_reason=%s,used_calls=%s,result_message=%s,result_sha256=%s WHERE task_id=%s",
                    (
                        phase,
                        None
                        if phase == "cancelled"
                        else result.get("held_reason", result["status"]),
                        calls,
                        Jsonb(message),
                        digest(message),
                        row["task_id"],
                    ),
                )
                if phase == "cancelled":
                    self.cancelled_in(c, owner, row["job_id"], row["attempt_id"])
            return self.runtime.get(owner, row["job_id"])
        if row["adoption_result"] is None:
            if envelope["role"] == "translation":
                adoption = self._translation_adoption(
                    owner, command, row, message, packet, result
                )
            else:
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
                        "UPDATE model_role_tasks SET phase=CASE WHEN phase='cancelled' THEN phase ELSE 'adopting' END,used_calls=%s,result_message=%s,result_sha256=%s,adoption_result=%s WHERE task_id=%s",
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
                "UPDATE model_role_tasks SET phase=CASE WHEN phase IN ('cancelled','accepted') THEN phase ELSE %s END WHERE task_id=%s",
                ("accepted" if accepted else "held", row["task_id"]),
            )
        return state

    @staticmethod
    def cancelled_in(c, owner, job_id, attempt_id):
        # Caller holds the product job lock. Cancellation is terminal independent
        # of the result/cancel-ACK arrival order; other native work must still drain.
        c.execute(
            "UPDATE model_role_tasks SET phase='cancelled',held_reason=NULL WHERE owner_id=%s AND job_id=%s AND attempt_id=%s AND phase!='accepted'",
            (owner, job_id, attempt_id),
        )
        c.execute(
            "UPDATE node_runs SET status='cancelled',completed_at=now(),lease_owner=NULL,lease_expires_at=NULL WHERE owner_id=%s AND job_id=%s AND id=%s AND status='running'",
            (owner, job_id, attempt_id),
        )
        running = c.execute(
            "SELECT count(*) n FROM node_runs r WHERE owner_id=%s AND job_id=%s AND (status='running' OR EXISTS (SELECT 1 FROM broker_dispatch_queue q WHERE q.node_run_id=r.id AND q.phase IN ('sending','sent','received','unknown')))",
            (owner, job_id),
        ).fetchone()["n"]
        if not running:
            c.execute(
                "UPDATE jobs SET status='cancelled',active_claim_id=NULL,updated_at=now()WHERE owner_id=%s AND id=%s AND cancel_requested=true",
                (owner, job_id),
            )

    def dispatch_next(self, owner, job_id):
        # Only the application orchestrator chooses and reserves the next node.
        return self.runtime.claim_next(owner, job_id)

    def _translation_envelope(self, owner, command):
        from ..postgres.translation import languages, segments
        from ..transcript_batches import validate_source

        config = command["translation"]
        pins = config["candidates"]
        if command["agent"]["id"] != "translate" or not 1 <= len(pins) <= 4:
            raise Conflict("invalid_translation_role_binding")
        reference = command["inputs"]["transcript"]
        raw = self.runtime.store.read(
            owner, reference, limit=min(reference["bytes"], 16 * 1024 * 1024)
        )
        source = json.loads(raw)
        validate_source(source)
        languages(config["source_language"], config["target_language"])
        batch_policy = config.get("batch_policy", "single_100x16k_v1")
        if batch_policy != "bounded_100x16k_v1":
            batch_policy = "single_100x16k_v1"
            segments([{k: v for k, v in r.items() if k != "id"} for r in source])
        cap = config.get("max_model_calls", len(pins))
        if type(cap) is not int or cap < 1:
            raise Conflict("invalid_role_frozen_call_budget")
        return {
            "version": 1,
            "role": "translation",
            "task": {
                "version": 1,
                "task_id": command["attempt_id"],
                "role": "translation",
                "transcript": {k: reference[k] for k in ["sha256", "bytes"]},
                "models": [{k: p[k] for k in ["model_id", "revision"]} for p in pins],
                "source_language": config["source_language"],
                "target_language": config["target_language"],
                "batch_policy": batch_policy,
                "max_calls": cap,
            },
            "source": {"owner": owner, "reference": reference},
            "output_owner": owner,
        }, pins

    def _translation_adoption(self, owner, command, row, message, packet, result):
        from ..transcript_batches import split_transcript, validate_source

        source = json.loads(
            self.runtime.store.read(
                owner,
                command["inputs"]["transcript"],
                limit=min(command["inputs"]["transcript"]["bytes"], 16 * 1024 * 1024),
            )
        )
        translated = result["segments"]
        validate_source(translated)
        if len(source) != len(translated) or any(
            {k: v for k, v in a.items() if k != "text"}
            != {k: v for k, v in b.items() if k != "text"}
            for a, b in zip(source, translated)
        ):
            raise Conflict("role_translation_source_structure_changed")
        task = row["envelope"]["task"]
        batches = list(split_transcript(source))
        chunks = result["chunks"]
        if len(chunks) != len(batches) or result["completed_chunks"] != len(batches):
            raise Conflict("role_translation_batch_coverage_changed")
        for chunk, batch in zip(chunks, batches):
            candidate = chunk["candidate_index"]
            if (
                type(candidate) is not int
                or not 0 <= candidate < len(task["models"])
                or chunk
                != {
                    "index": batch.chunk_index,
                    "start": batch.start,
                    "end": batch.end,
                    "input_sha256": batch.sha256,
                    "model": task["models"][candidate],
                    "candidate_index": candidate,
                }
            ):
                raise Conflict("role_translation_batch_binding_changed")
        if (
            result["source_language"] != task["source_language"]
            or result["target_language"] != task["target_language"]
        ):
            raise Conflict("role_translation_language_changed")
        output = self.runtime.store.put(owner, [canonical(translated)], "transcript")
        selected = row["frozen_candidates"][chunks[-1]["candidate_index"]]
        metadata = {
            "role_task_id": row["task_id"],
            "model_calls": result["model_calls"],
            "completed_chunks": len(chunks),
            "chunks": chunks,
            "source_language": task["source_language"],
            "target_language": task["target_language"],
            "tool_mode": packet["tool_mode"],
            "selected": {
                k: selected[k]
                for k in [
                    "model_id",
                    "revision",
                    "connection_id",
                    "connection_revision",
                    "remote_model",
                    "protocol",
                ]
            },
            "result_ref": message["result_ref"],
        }
        return {
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
            "outputs": {"transcript": output},
            "transport": "independent_model_role",
            "translation": metadata,
        }
