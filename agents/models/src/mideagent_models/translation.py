"""Role-local LangGraph translation; reuse the existing bounded wire and decoder.

Owns batching/candidate decisions/state, receives no global DB or provider keys.
"""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from video_service.cpu_agents import canonical
from video_service.model_endpoints import EndpointFailure
from video_service.postgres.translation import (
    ADVANCE,
    languages,
    segments,
    translated_segments,
)
from video_service.transcript_batches import split_transcript, validate_source

from .state import RoleState
from .task_tools import invoke as invoke_tool
from video_service.task_agents import registration


class TranslationState(TypedDict, total=False):
    task: dict
    batches: list
    batch: int
    candidate: int
    call_index: int
    status: str
    reply: str
    result: dict
    audio_path: str
    pending: dict
    document: dict


class TranslationAgent:
    role = "translation"
    registration = registration("translate")

    def __init__(self, root, model_tool, *, chunk_concurrency=1):
        if type(chunk_concurrency) is not int or chunk_concurrency < 1:
            raise ValueError("positive_chunk_concurrency_required")
        self.root = Path(root).resolve()
        self.state = RoleState(self.root)
        self.model_tool = model_tool
        self.call_slots = threading.BoundedSemaphore(chunk_concurrency)
        self.connection = sqlite3.connect(
            self.root / "graph-checkpoints.sqlite", check_same_thread=False
        )
        self.saver = SqliteSaver(
            self.connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[])
        )
        graph = StateGraph(TranslationState)
        for name in [
            "prepare",
            "select",
            "invoke",
            "validate",
            "advance",
            "finish",
            "hold",
            "cancelled",
        ]:
            graph.add_node(name, getattr(self, "_" + name))
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges(
            "prepare",
            lambda s: s["status"],
            {"ready": "select", "held": "hold", "cancelled": "cancelled"},
        )
        graph.add_conditional_edges(
            "select",
            lambda s: s["status"],
            {
                "ready": "invoke",
                "received": "validate",
                "cached": "advance",
                "completed": "finish",
                "held": "hold",
                "cancelled": "cancelled",
            },
        )
        graph.add_conditional_edges(
            "invoke",
            lambda s: s["status"],
            {
                "received": "validate",
                "retry": "select",
                "held": "hold",
                "cancelled": "cancelled",
            },
        )
        graph.add_conditional_edges(
            "validate",
            lambda s: s["status"],
            {"cached": "advance", "retry": "select", "held": "hold"},
        )
        graph.add_edge("advance", "select")
        for name in ["finish", "hold", "cancelled"]:
            graph.add_edge(name, END)
        self.graph = graph.compile(checkpointer=self.saver)

    def graph_nodes(self):
        return set(self.graph.get_graph().nodes)

    def checkpoint(self, task):
        return self.graph.get_state({"configurable": {"thread_id": task}}).values

    def cancel(self, task):
        return self.state.cancel(task)

    def prepare_task(self, task, path):
        from .protocol import validate_translation_task

        validate_translation_task(task)
        raw = Path(path).read_bytes()
        if (
            len(raw) != task["transcript"]["bytes"]
            or hashlib.sha256(raw).hexdigest() != task["transcript"]["sha256"]
        ):
            raise ValueError("transcript_input_mismatch")
        source = json.loads(raw)
        validate_source(source)
        languages(task["source_language"], task["target_language"])
        if task["batch_policy"] == "single_100x16k_v1":
            segments([{k: v for k, v in r.items() if k != "id"} for r in source])
        self.state.ensure(
            task["task_id"], hashlib.sha256(canonical(task)).hexdigest(), task
        )
        return invoke_tool(self, task, "text.prepare_batches", lambda: list(split_transcript(source)))

    def run(self, task, path):
        with self.state.lock(task["task_id"], "execution"):
            batches = self.prepare_task(task, path)
            prior = self.state.task(task["task_id"])
            if prior["status"] == "completed" and not prior["cancelled"]:
                return json.loads(prior["result"])
            return self.graph.invoke(
                {"task": task, "batches": batches, "batch": 0, "status": "new"},
                config={
                    "configurable": {"thread_id": task["task_id"]},
                    "recursion_limit": len(batches) * len(task["models"]) * 5 + 12,
                },
            )["result"]

    def _prepare(self, s):
        return {
            "status": "cancelled"
            if self.state.cancelled(s["task"]["task_id"])
            else "held"
            if len(s["batches"]) > s["task"]["max_calls"]
            else "ready"
        }

    def _select(self, s):
        task = s["task"]
        identifier = task["task_id"]
        if self.state.cancelled(identifier):
            return {"status": "cancelled"}
        if s["batch"] >= len(s["batches"]):
            return {"status": "completed"}
        for candidate in range(len(task["models"])):
            index = s["batch"] * len(task["models"]) + candidate
            row = self.state.chunk(identifier, index)
            choice = {"candidate": candidate, "call_index": index}
            if not row:
                return {
                    **choice,
                    "status": "held"
                    if self.state.task(identifier)["status"] == "held"
                    else "ready",
                }
            if row["status"] == "completed":
                return {**choice, "status": "cached"}
            if row["status"] == "received":
                return {
                    **choice,
                    "status": "received",
                    "reply": json.loads(row["reply"]),
                }
            if row["status"] == "started":
                self.state.fail(identifier, index, "interrupted_model_intent", True)
            if row["status"] != "failed" or row["error"] not in ADVANCE:
                return {"status": "held"}
        return {"status": "held"}

    def _invoke(self, s):
        task = s["task"]
        identifier = task["task_id"]
        index = s["call_index"]
        with self.call_slots, self.state.lock(identifier, "call-fence", shared=True):
            reserved = self.state.reserve(identifier, index)
            if reserved == "cancelled":
                return {"status": "cancelled"}
            if reserved != "reserved":
                return {"status": "held"}
            if self.state.cancelled(identifier):
                return {"status": "cancelled"}
            try:
                reply = invoke_tool(
                    self, task, "text.translate",
                    lambda: self.model_tool(task, s["batches"][s["batch"]], s["candidate"]),
                    index=index,
                )
            except Exception as error:
                self.state.fail(identifier, index, type(error).__name__, True)
                return {"status": "held"}
            if reply.get("status") == "received" and type(reply.get("reply")) is str:
                self.state.reply(identifier, index, reply["reply"])
                return {"status": "received", "reply": reply["reply"]}
            if reply.get("status") == "failed":
                self.state.candidate_failed(identifier, index, reply["error"])
                return {"status": "retry"}
            self.state.fail(
                identifier, index, reply.get("error", "model_reply_unknown"), True
            )
            return {"status": "held"}

    def _validate(self, s):
        batch = s["batches"][s["batch"]]
        source = batch.segments
        try:
            def validate():
                plain = [{k: v for k, v in row.items() if k != "id"} for row in source]
                parsed = translated_segments(s["reply"], plain)
                rows = [{**before, "text": after["text"]} for before, after in zip(source, parsed)]
                return validate_source(rows)
            rows = invoke_tool(self, s["task"], "text.validate_batch", validate, index=s["call_index"])
        except (ValueError, EndpointFailure):
            self.state.candidate_failed(
                s["task"]["task_id"], s["call_index"], "invalid_response"
            )
            return {"status": "retry"}
        self.state.complete(s["task"]["task_id"], s["call_index"], rows)
        return {"status": "cached"}

    def _advance(self, s):
        return {"batch": s["batch"] + 1, "status": "ready"}

    def _terminal(self, s, status, **extra):
        task = s["task"]
        result = {
            "version": 1,
            "task_id": task["task_id"],
            "role": self.role,
            "status": status,
            "completed_chunks": 0,
            "model_calls": self.state.task(task["task_id"])["calls"],
            **extra,
        }
        if status == "held":
            result["held_reason"] = self.role + "_checkpoint_held"
        result = self.state.finish(task["task_id"], result)
        return {"result": result, "status": result["status"]}

    def _finish(self, s):
        if self.state.cancelled(s["task"]["task_id"]):
            return self._cancelled(s)
        result = invoke_tool(self, s["task"], "text.merge_batches", lambda: self._assemble(s))
        return self._terminal(s, "completed", **result)

    def _assemble(self, s):
        task = s["task"]
        rows = []
        chunks = []
        for batch in s["batches"]:
            for candidate, model in enumerate(task["models"]):
                row = self.state.chunk(
                    task["task_id"], batch.chunk_index * len(task["models"]) + candidate
                )
                if row and row["status"] == "completed":
                    rows.extend(json.loads(row["result"]))
                    chunks.append(
                        {
                            "index": batch.chunk_index,
                            "start": batch.start,
                            "end": batch.end,
                            "input_sha256": batch.sha256,
                            "model": model,
                            "candidate_index": candidate,
                        }
                    )
                    break
        validate_source(rows)
        expected = [row for batch in s["batches"] for row in batch.segments]
        if len(rows) != len(expected) or any(
            {k:v for k,v in before.items() if k != "text"} !=
            {k:v for k,v in after.items() if k != "text"}
            for before,after in zip(expected,rows)
        ):
            raise ValueError("translation_source_identity_changed")
        return dict(segments=rows, chunks=chunks, completed_chunks=len(chunks),
                    source_language=task["source_language"], target_language=task["target_language"])

    def _hold(self, s):
        return self._terminal(s, "held")

    def _cancelled(self, s):
        return self._terminal(s, "cancelled")
