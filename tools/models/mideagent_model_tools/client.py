"""Trusted application credential bridge. Not a graph/Execution wrapper.

It resolves only the already-frozen candidate and verifies the exact chunk grant.
The independent role owns graph transitions, segmentation, checkpoints and result.
No provider key/master key or global database capability is given to the role.
"""

import base64
import hashlib
import threading

from psycopg.types.json import Jsonb

from video_service.audio_batches import split_normalized_audio
from video_service.audio_contract import timed_segments
from mideagent_model_tools.endpoints import EndpointFailure
from video_service.postgres import Conflict
from video_service.canonical import canonical
from video_service.role_policy import attempt_index, endpoint_error_code, is_v2, model_binding, tool_context, validate_predecessors


class RoleToolBridge:
    def __init__(self, roles, *, chunk_concurrency):
        if type(chunk_concurrency) is not int or chunk_concurrency < 1:
            raise ValueError("positive_bridge_concurrency_required")
        self.roles = roles
        self.slots = threading.BoundedSemaphore(chunk_concurrency)

    @staticmethod
    def _packet_context(packet, task, legacy_keys):
        expected = tool_context(task)
        keys = legacy_keys | set(expected)
        if task["role"] == "transcription" and is_v2(task):
            keys |= {"candidate_index"}
        if set(packet) != keys or any(type(packet[k]) is not type(v) or packet[k] != v for k, v in expected.items()):
            raise Conflict("tool_policy_or_task_outside_grant")

    @staticmethod
    def _predecessors(c, task, chunk, candidate, source_sha):
        # This check and the insertion below MUST share the task advisory xact lock.
        history = c.execute(
            "SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index",
            (task["task_id"],),
        ).fetchall()
        try:
            validate_predecessors(history, chunk, candidate, task["models"], source_sha)
        except ValueError as error:
            raise Conflict(str(error)) from None

    @staticmethod
    def _translation_response(c, task, batch, index, reply):
        """Revalidate a durably received response without another provider intent."""
        from video_service.translation_output import OutputCapacityError, decode_output

        try:
            decode_output(reply, batch.segments)
        except OutputCapacityError:
            # A known response exceeds output capacity. Keep completed+response;
            # no following candidate may spend around it.
            return {"status": "received", "reply": reply}
        except (ValueError, TypeError, RecursionError):
            c.execute(
                "UPDATE model_role_tool_calls SET status='failed',error_code='invalid_response' WHERE task_id=%s AND chunk_index=%s AND status='completed'",
                (task["task_id"], index),
            )
            return {"status": "failed", "error": "invalid_response"}
        return {"status": "received", "reply": reply}

    def invoke(self, packet):
        legacy_keys = {"task_id", "chunk_index", "model", "source_language", "audio_base64"}
        if (
            type(packet) is not dict
            or set(packet)
            not in (legacy_keys, legacy_keys | {"version", "role_policy_version", "task_sha256", "candidate_index"})
            or type(packet["chunk_index"]) is not int
            or packet["chunk_index"] < 0
        ):
            raise ValueError("invalid_scoped_tool_request")
        raw = base64.b64decode(packet["audio_base64"], validate=True)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("tool_audio_budget_exceeded")
        runtime = self.roles.runtime
        with runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
            ).fetchone()
            if not row or row["envelope"]["role"] != "transcription" or row["phase"] not in {
                "sending",
                "sent",
                "adopting",
                "accepted",
            }:
                raise Conflict("tool_grant_not_active")
            task = row["envelope"]["task"]
            owner = row["owner_id"]
            command = c.execute(
                "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row["job_id"], row["attempt_id"]),
            ).fetchone()["request"]
        self._packet_context(packet, task, legacy_keys)
        v2 = is_v2(task)
        candidate = packet.get("candidate_index", 0)
        if type(candidate) is not int or not 0 <= candidate < (len(task["models"]) if v2 else 1):
            raise Conflict("tool_model_outside_grant")
        model = task["models"][candidate] if v2 else task["model"]
        if (
            (canonical(packet["model"]) != canonical(model) if v2 else packet["model"] != model)
            or packet["source_language"] != task["source_language"]
        ):
            raise Conflict("tool_model_or_language_outside_grant")
        # Verify exact admitted source bytes, not only the caller-declared chunk hash.
        reference = command["inputs"]["audio"]
        if (
            type(reference["bytes"]) is not int
            or not 0 < reference["bytes"] <= 1024 * 1024 * 1024
        ):
            raise Conflict("tool_source_audio_budget_exceeded")
        source = runtime.store.read(owner, reference, limit=reference["bytes"])
        if v2:
            from video_service.role_receipts import speech_chunks

            admitted_chunks = speech_chunks(task, source)
        else:
            admitted_chunks = split_normalized_audio(source)
        chunk = next(
            (
                v
                for v in admitted_chunks
                if v.chunk_index == packet["chunk_index"]
            ),
            None,
        )
        if chunk is None or chunk.audio != raw:
            raise Conflict("tool_chunk_outside_grant")
        sha = hashlib.sha256(raw).hexdigest()
        pin = row["frozen_candidates"][candidate]
        if v2 and canonical(model_binding(pin)) != canonical(model):
            raise Conflict("tool_frozen_pin_changed")
        index = attempt_index(packet["chunk_index"], candidate, len(task["models"])) if v2 else packet["chunk_index"]
        with self.slots:
            with runtime.database.connection() as c:
                c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("role-tool:" + row["task_id"],),
                )
                prior = c.execute(
                    "SELECT * FROM model_role_tool_calls WHERE task_id=%s AND chunk_index=%s",
                    (row["task_id"], index),
                ).fetchone()
                if prior:
                    if prior["input_sha256"] != sha or prior["model"] != model:
                        raise Conflict("immutable_tool_call_changed")
                    if prior["status"] == "completed":
                        response = timed_segments(prior["response"], chunk.end - chunk.start) if v2 else prior["response"]
                        return {"status": "received", "reply": response} if v2 else response
                    if v2 and prior["status"] == "failed":
                        return {"status": "failed", "error": prior["error_code"]}
                    raise Conflict("tool_call_unknown_or_settled_no_recall")
                if v2:
                    self._predecessors(c, task, packet["chunk_index"], candidate, sha)
                self.roles._current(c, owner, command)
                used = c.execute(
                    "SELECT count(*) n FROM model_role_tool_calls WHERE task_id=%s",
                    (row["task_id"],),
                ).fetchone()["n"]
                if used >= task["max_calls"]:
                    raise Conflict("tool_total_call_budget_exhausted")
                c.execute(
                    "INSERT INTO model_role_tool_calls(task_id,chunk_index,input_sha256,model,status)VALUES(%s,%s,%s,%s,'started')",
                    (row["task_id"], index, sha, Jsonb(model)),
                )
            executor = runtime.transcription_runtime
            adapter = None
            close_error = None
            try:
                if (
                    executor.requires_paid([pin])
                    and not command["transcription"]["paid_authorized"]
                ):
                    raise Conflict("paid_authorization_required")
                if not executor.available(pin):
                    if v2:
                        raise EndpointFailure("frozen model unavailable", code="unavailable")
                    raise Conflict("frozen_registered_model_unavailable")
                key = (
                    executor.credentials.resolve(
                        pin["owner_id"], pin["connection_id"], pin["credential_ref"]
                    )
                    if pin["credential_ref"]
                    else None
                )
                adapter = executor.make_adapter(pin, key)
                from video_service.postgres.model_call_fence import model_call_fence

                # The shared session fence survives the final row-lock transaction
                # and actual adapter entry. Product cancel takes its exclusive side.
                with model_call_fence(runtime.database, owner, command["run_id"]):
                    with runtime.database.connection() as c:
                        self.roles._current(c, owner, command)
                    received = adapter.transcribe(pin["remote_model"], raw, task["source_language"])
                    try:
                        response = timed_segments(received, chunk.end - chunk.start)
                    except (ValueError, TypeError, KeyError):
                        if v2:
                            raise EndpointFailure("invalid timed transcription", code="invalid_response") from None
                        raise
            except Exception as error:
                code = (
                    endpoint_error_code(error, v2=v2)
                    if isinstance(error, EndpointFailure)
                    else type(error).__name__
                )
                with runtime.database.connection() as c:
                    c.execute(
                        "UPDATE model_role_tool_calls SET status=%s,error_code=%s WHERE task_id=%s AND chunk_index=%s",
                        (
                            "failed"
                            if isinstance(error, (EndpointFailure, Conflict))
                            and code != "outcome_unknown"
                            else "unknown",
                            code,
                            row["task_id"],
                            index,
                        ),
                    )
                if v2:
                    known = isinstance(error, (EndpointFailure, Conflict)) and code != "outcome_unknown"
                    return {"status": "failed" if known else "unknown", "error": code}
                raise
            finally:
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception as error:
                        if not v2:
                            raise
                        close_error = error
            with runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_tool_calls SET status='completed',response=%s WHERE task_id=%s AND chunk_index=%s AND status='started'",
                    (Jsonb(response), row["task_id"], index),
                )
            if close_error is not None:
                raise close_error
            return {"status": "received", "reply": response} if v2 else response

    def invoke_translation(self, packet):
        from video_service.postgres.model_call_fence import model_call_fence
        from video_service.postgres.translation import translation_messages
        from video_service.transcript_batches import split_transcript

        legacy_keys = {"task_id", "batch_index", "candidate_index", "model", "input_sha256"}
        if (
            type(packet) is not dict
            or set(packet)
            not in (legacy_keys, legacy_keys | {"version", "role_policy_version", "task_sha256"}, legacy_keys | {"version", "role_policy_version", "task_sha256", "translation_context_version"})
            or any(
                type(packet[k]) is not int or packet[k] < 0
                for k in ["batch_index", "candidate_index"]
            )
        ):
            raise ValueError("invalid_scoped_translation_request")
        runtime = self.roles.runtime
        with runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
            ).fetchone()
            if (
                not row
                or row["envelope"]["role"] != "translation"
                or row["phase"] not in {"sending", "sent", "adopting", "accepted"}
            ):
                raise Conflict("tool_translation_grant_not_active")
            task = row["envelope"]["task"]
            owner = row["owner_id"]
            command = c.execute(
                "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row["job_id"], row["attempt_id"]),
            ).fetchone()["request"]
        from video_service.role_task_contracts import validate_translation_task
        validate_translation_task(task)
        self._packet_context(packet, task, legacy_keys)
        if task.get("translation_context") != command["translation"].get("translation_context"):
            raise Conflict("tool_translation_context_changed")
        if "translation_context" in task and getattr(runtime.translation_runtime, "translation_context_version", None) != 1:
            raise Conflict("translation_context_bridge_not_enabled")
        v2 = is_v2(task)
        candidate = packet["candidate_index"]
        if (
            not 0 <= candidate < len(task["models"])
            or (canonical(packet["model"]) != canonical(task["models"][candidate]) if v2 else packet["model"] != task["models"][candidate])
        ):
            raise Conflict("tool_model_outside_grant")
        reference = command["inputs"]["transcript"]
        raw_source = runtime.store.read(
            owner, reference, limit=min(reference["bytes"], 16 * 1024 * 1024)
        )
        if v2 and (len(raw_source) != task["transcript"]["bytes"] or hashlib.sha256(raw_source).hexdigest() != task["transcript"]["sha256"]):
            raise Conflict("tool_translation_source_changed")
        source = __import__("json").loads(raw_source)
        batch = next(
            (
                b
                for b in split_transcript(source, policy_version=2 if v2 else 1)
                if b.chunk_index == packet["batch_index"]
            ),
            None,
        )
        if batch is None or batch.sha256 != packet["input_sha256"]:
            raise Conflict("tool_translation_batch_outside_grant")
        index = batch.chunk_index * len(task["models"]) + candidate
        pin = row["frozen_candidates"][candidate]
        if v2 and canonical(model_binding(pin)) != canonical(packet["model"]):
            raise Conflict("tool_frozen_pin_changed")
        with self.slots:
            with runtime.database.connection() as c:
                c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("role-tool:" + row["task_id"],),
                )
                prior = c.execute(
                    "SELECT * FROM model_role_tool_calls WHERE task_id=%s AND chunk_index=%s",
                    (row["task_id"], index),
                ).fetchone()
                if prior:
                    if (
                        prior["input_sha256"] != batch.sha256
                        or prior["model"] != packet["model"]
                    ):
                        raise Conflict("immutable_tool_call_changed")
                    if prior["status"] == "completed":
                        if v2:
                            return self._translation_response(c, task, batch, index, prior["response"])
                        return {"status": "received", "reply": prior["response"]}
                    if prior["status"] == "failed":
                        return {"status": "failed", "error": prior["error_code"]}
                    raise Conflict("tool_call_unknown_or_settled_no_recall")
                if v2:
                    self._predecessors(c, task, batch.chunk_index, candidate, batch.sha256)
                self.roles._current(c, owner, command)
                used = c.execute(
                    "SELECT count(*)n FROM model_role_tool_calls WHERE task_id=%s",
                    (row["task_id"],),
                ).fetchone()["n"]
                if used >= task["max_calls"]:
                    raise Conflict("tool_total_call_budget_exhausted")
                c.execute(
                    "INSERT INTO model_role_tool_calls(task_id,chunk_index,input_sha256,model,status)VALUES(%s,%s,%s,%s,'started')",
                    (row["task_id"], index, batch.sha256, Jsonb(packet["model"])),
                )
            executor = runtime.translation_runtime
            adapter = None
            close_error = None
            try:
                if (
                    executor.requires_paid([pin])
                    and not command["translation"]["paid_authorized"]
                ):
                    raise Conflict("paid_authorization_required")
                if not executor.available(pin):
                    raise EndpointFailure(
                        "frozen model unavailable", code="unavailable"
                    )
                key = (
                    executor.credentials.resolve(
                        pin["owner_id"], pin["connection_id"], pin["credential_ref"]
                    )
                    if pin["credential_ref"]
                    else None
                )
                adapter = executor.make_adapter(pin, key)
                if "inference" not in pin:
                    adapter._client.timeout = 15.0
                plain = [
                    {k: v for k, v in r.items() if k != "id"} for r in batch.segments
                ]
                messages = translation_messages(
                    plain, task["source_language"], task["target_language"],
                    **({"translation_context": task["translation_context"]} if "translation_context" in task else {})
                )
                with model_call_fence(runtime.database, owner, command["run_id"]):
                    with runtime.database.connection() as c:
                        self.roles._current(c, owner, command)
                    reply = adapter.chat(pin["remote_model"], messages)
            except Exception as error:
                code = (
                    endpoint_error_code(error, v2=v2)
                    if isinstance(error, EndpointFailure)
                    else str(error)
                    if isinstance(error, Conflict)
                    else type(error).__name__
                )
                known = (
                    isinstance(error, (EndpointFailure, Conflict))
                    and code != "outcome_unknown"
                )
                with runtime.database.connection() as c:
                    c.execute(
                        "UPDATE model_role_tool_calls SET status=%s,error_code=%s WHERE task_id=%s AND chunk_index=%s",
                        ("failed" if known else "unknown", code, row["task_id"], index),
                    )
                return {"status": "failed" if known else "unknown", "error": code}
            finally:
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception as error:
                        if not v2:
                            raise
                        close_error = error
            with runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_tool_calls SET status='completed',response=%s WHERE task_id=%s AND chunk_index=%s AND status='started'",
                    (Jsonb(reply), row["task_id"], index),
                )
            if close_error is not None:
                raise close_error
            if v2:
                # Receipt commit precedes output decoding. A decoder or process
                # failure leaves a reusable response, never a new paid intent.
                with runtime.database.connection() as c:
                    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("role-tool:" + task["task_id"],))
                    return self._translation_response(c, task, batch, index, reply)
            return {"status": "received", "reply": reply}

    def invoke_vocalization(self, packet):
        from video_service.postgres.model_call_fence import model_call_fence
        from video_service.vocal_role_plan import vocal_plan

        if (
            type(packet) is not dict
            or set(packet)
            != {"task_id", "call_index", "candidate_index", "model", "input_sha256"}
            or any(
                type(packet[k]) is not int or packet[k] < 0
                for k in ["call_index", "candidate_index"]
            )
        ):
            raise ValueError("invalid_scoped_translation_request")
        runtime = self.roles.runtime
        with runtime.database.connection() as c:
            row = c.execute(
                "SELECT * FROM model_role_tasks WHERE task_id=%s", (packet["task_id"],)
            ).fetchone()
            if (
                not row
                or row["envelope"]["role"] != "vocalization"
                or row["phase"] not in {"sending", "sent", "adopting", "accepted"}
            ):
                raise Conflict("tool_vocal_grant_not_active")
            task = row["envelope"]["task"]
            owner = row["owner_id"]
            command = c.execute(
                "SELECT request FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, row["job_id"], row["attempt_id"]),
            ).fetchone()["request"]
        candidate = packet["candidate_index"]
        if (
            not 0 <= candidate < len(task["models"])
            or packet["model"] != task["models"][candidate]
        ):
            raise Conflict("tool_model_outside_grant")
        reference = command["inputs"]["audio"]
        streamed = task.get("batch_policy") == "streamed_vocalization_v2"
        if (
            not 0
            < reference["bytes"]
            <= (1024 * 1024 * 1024 if streamed else 300 * 32000 + 65536)
        ):
            raise Conflict("vocal_existing_audio_budget_exceeded")
        raw = (
            runtime.store.path(owner, reference)
            if streamed
            else runtime.store.read(owner, reference, limit=reference["bytes"])
        )
        width = len(task["models"])
        with runtime.database.connection() as c:
            history = c.execute(
                "SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index",
                (task["task_id"],),
            ).fetchall()

        def completed(call):
            matches = [
                r
                for r in history
                if r["chunk_index"] // width == call and r["status"] == "completed"
            ]
            return (True, matches[0]["response"]) if matches else (False, None)

        plan = vocal_plan(raw, task, completed)
        index = packet["call_index"] * width + candidate
        pin = row["frozen_candidates"][candidate]
        prior = next((r for r in history if r["chunk_index"] == index), None)
        if prior:
            if (
                prior["input_sha256"] != packet["input_sha256"]
                or prior["model"] != packet["model"]
            ):
                raise Conflict("immutable_tool_call_changed")
            if prior["status"] == "completed":
                return {"status": "received", "reply": prior["response"]}
            if prior["status"] == "failed":
                return {"status": "failed", "error": prior["error_code"]}
            raise Conflict("tool_call_unknown_or_settled_no_recall")
        if (
            "pending" not in plan
            or plan["pending"]["context"]["call_index"] != packet["call_index"]
            or plan["pending"]["input_sha256"] != packet["input_sha256"]
        ):
            raise Conflict("vocal_tool_call_outside_grant")
        request = plan["pending"]
        sha = request["input_sha256"]
        with self.slots:
            with runtime.database.connection() as c:
                c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("role-tool:" + row["task_id"],),
                )
                prior = c.execute(
                    "SELECT * FROM model_role_tool_calls WHERE task_id=%s AND chunk_index=%s",
                    (row["task_id"], index),
                ).fetchone()
                if prior:
                    if (
                        prior["input_sha256"] != sha
                        or prior["model"] != packet["model"]
                    ):
                        raise Conflict("immutable_tool_call_changed")
                    if prior["status"] == "completed":
                        return {"status": "received", "reply": prior["response"]}
                    if prior["status"] == "failed":
                        return {"status": "failed", "error": prior["error_code"]}
                    raise Conflict("tool_call_unknown_or_settled_no_recall")
                self.roles._current(c, owner, command)
                used = c.execute(
                    "SELECT count(*)n FROM model_role_tool_calls WHERE task_id=%s",
                    (row["task_id"],),
                ).fetchone()["n"]
                if used >= task["max_calls"]:
                    raise Conflict("tool_total_call_budget_exhausted")
                c.execute(
                    "INSERT INTO model_role_tool_calls(task_id,chunk_index,input_sha256,model,status)VALUES(%s,%s,%s,%s,'started')",
                    (row["task_id"], index, sha, Jsonb(packet["model"])),
                )
            executor = runtime.vocalization_runtime
            adapter = None
            try:
                if (
                    executor.requires_paid([pin])
                    and not command["vocalization"]["paid_authorized"]
                ):
                    raise Conflict("paid_authorization_required")
                if not executor.available(pin):
                    raise EndpointFailure(
                        "frozen model unavailable", code="unavailable"
                    )
                key = (
                    executor.credentials.resolve(
                        pin["owner_id"], pin["connection_id"], pin["credential_ref"]
                    )
                    if pin["credential_ref"]
                    else None
                )
                adapter = executor.make_adapter(pin, key)
                if "inference" not in pin:
                    adapter._client.timeout = 15.0
                with model_call_fence(runtime.database, owner, command["run_id"]):
                    with runtime.database.connection() as c:
                        self.roles._current(c, owner, command)
                    reply = adapter.classify(
                        pin["remote_model"],
                        request["context"],
                        plan["clips"],
                        request["schema"],
                    )
            except Exception as error:
                code = (
                    error.code
                    if isinstance(error, EndpointFailure)
                    else str(error)
                    if isinstance(error, Conflict)
                    else type(error).__name__
                )
                known = (
                    isinstance(error, (EndpointFailure, Conflict))
                    and code != "outcome_unknown"
                )
                with runtime.database.connection() as c:
                    c.execute(
                        "UPDATE model_role_tool_calls SET status=%s,error_code=%s WHERE task_id=%s AND chunk_index=%s",
                        ("failed" if known else "unknown", code, row["task_id"], index),
                    )
                return {"status": "failed" if known else "unknown", "error": code}
            finally:
                if adapter is not None:
                    adapter.close()
            with runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_tool_calls SET status='completed',response=%s WHERE task_id=%s AND chunk_index=%s AND status='started'",
                    (Jsonb(reply), row["task_id"], index),
                )
            return {"status": "received", "reply": reply}
