"""Trusted application credential bridge. Not a graph/Execution wrapper.

It resolves only the already-frozen candidate and verifies the exact chunk grant.
The independent role owns graph transitions, segmentation, checkpoints and result.
No provider key/master key or global database capability is given to the role.
"""

import base64
import hashlib
import threading

from psycopg.types.json import Jsonb

from .audio_batches import split_normalized_audio
from .audio_contract import timed_segments
from .model_endpoints import EndpointFailure
from .postgres import Conflict


class RoleToolBridge:
    def __init__(self, roles, *, chunk_concurrency):
        if type(chunk_concurrency) is not int or chunk_concurrency < 1:
            raise ValueError("positive_bridge_concurrency_required")
        self.roles = roles
        self.slots = threading.BoundedSemaphore(chunk_concurrency)

    def invoke(self, packet):
        if (
            type(packet) is not dict
            or set(packet)
            != {"task_id", "chunk_index", "model", "source_language", "audio_base64"}
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
            if not row or row["phase"] not in {
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
        if (
            packet["model"] != task["model"]
            or packet["source_language"] != task["source_language"]
        ):
            raise Conflict("tool_model_or_language_outside_grant")
        # Verify exact admitted source bytes, not only the caller-declared chunk hash.
        source = runtime.store.read(
            owner, command["inputs"]["audio"], limit=1024 * 1024 * 1024
        )
        chunk = next(
            (
                v
                for v in split_normalized_audio(source)
                if v.chunk_index == packet["chunk_index"]
            ),
            None,
        )
        if chunk is None or chunk.audio != raw:
            raise Conflict("tool_chunk_outside_grant")
        sha = hashlib.sha256(raw).hexdigest()
        pin = row["frozen_candidates"][0]
        with self.slots:
            with runtime.database.connection() as c:
                c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("role-tool:" + row["task_id"],),
                )
                prior = c.execute(
                    "SELECT * FROM model_role_tool_calls WHERE task_id=%s AND chunk_index=%s",
                    (row["task_id"], packet["chunk_index"]),
                ).fetchone()
                if prior:
                    if prior["input_sha256"] != sha or prior["model"] != task["model"]:
                        raise Conflict("immutable_tool_call_changed")
                    if prior["status"] == "completed":
                        return prior["response"]
                    raise Conflict("tool_call_unknown_or_settled_no_recall")
                self.roles._current(c, owner, command)
                used = c.execute(
                    "SELECT count(*) n FROM model_role_tool_calls WHERE task_id=%s",
                    (row["task_id"],),
                ).fetchone()["n"]
                if used >= task["max_calls"]:
                    raise Conflict("tool_total_call_budget_exhausted")
                c.execute(
                    "INSERT INTO model_role_tool_calls(task_id,chunk_index,input_sha256,model,status)VALUES(%s,%s,%s,%s,'started')",
                    (row["task_id"], packet["chunk_index"], sha, Jsonb(task["model"])),
                )
            executor = runtime.transcription_runtime
            adapter = None
            try:
                if (
                    executor.requires_paid([pin])
                    and not command["transcription"]["paid_authorized"]
                ):
                    raise Conflict("paid_authorization_required")
                if not executor.available(pin):
                    raise Conflict("frozen_registered_model_unavailable")
                key = (
                    executor.credentials.resolve(
                        pin["owner_id"], pin["connection_id"], pin["credential_ref"]
                    )
                    if pin["credential_ref"]
                    else None
                )
                adapter = executor.make_adapter(pin, key)
                from .postgres.model_call_fence import model_call_fence

                # The shared session fence survives the final row-lock transaction
                # and actual adapter entry. Product cancel takes its exclusive side.
                with model_call_fence(runtime.database, owner, command["run_id"]):
                    with runtime.database.connection() as c:
                        self.roles._current(c, owner, command)
                    response = timed_segments(
                        adapter.transcribe(
                            pin["remote_model"], raw, task["source_language"]
                        ),
                        chunk.end - chunk.start,
                    )
            except Exception as error:
                code = (
                    error.code
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
                            packet["chunk_index"],
                        ),
                    )
                raise
            finally:
                if adapter is not None:
                    adapter.close()
            with runtime.database.connection() as c:
                c.execute(
                    "UPDATE model_role_tool_calls SET status='completed',response=%s WHERE task_id=%s AND chunk_index=%s AND status='started'",
                    (Jsonb(response), row["task_id"], packet["chunk_index"]),
                )
            return response
