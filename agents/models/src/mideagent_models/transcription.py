"""Independent speech role: its own LangGraph, task state and model tool boundary.

It receives one speech task, never a global job/workflow or database credential.
Transport/storage adapters supply a verified audio path and a scoped model tool.
"""

import hashlib
import io
import json
import math
import re
import sqlite3
import wave
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from video_service.audio_contract import timed_segments
from video_service.cpu_agents import canonical
from video_service.packed_projection import project, validate_projection_clock

from .state import RoleState


class SpeechState(TypedDict, total=False):
    task: dict
    chunks: list
    index: int
    status: str
    reply: list
    result: dict


class TranscriptionAgent:
    def __init__(self, root, model_tool):
        self.root = Path(root).resolve()
        self.state = RoleState(self.root)
        self.model_tool = model_tool
        self.connection = sqlite3.connect(
            self.root / "graph-checkpoints.sqlite", check_same_thread=False
        )
        self.saver = SqliteSaver(
            self.connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[])
        )
        graph = StateGraph(SpeechState)
        for name in [
            "prepare",
            "acquire",
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
            {"ready": "acquire", "cancelled": "cancelled", "held": "hold"},
        )
        graph.add_conditional_edges(
            "acquire",
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
            {"received": "validate", "held": "hold", "cancelled": "cancelled"},
        )
        graph.add_conditional_edges(
            "validate", lambda s: s["status"], {"cached": "advance", "held": "hold"}
        )
        graph.add_edge("advance", "acquire")
        for node in ["finish", "hold", "cancelled"]:
            graph.add_edge(node, END)
        self.graph = graph.compile(checkpointer=self.saver)

    def graph_nodes(self):
        return self.graph.get_graph().nodes

    def checkpoint(self, task):
        return self.graph.get_state({"configurable": {"thread_id": task}}).values

    def cancel(self, task):
        return self.state.cancel(task)

    def prepare_task(self, task, audio):
        keys = {
            "version",
            "task_id",
            "role",
            "audio",
            "model",
            "source_language",
            "chunk_frames",
            "max_calls",
            "timeline",
        }
        if (
            set(task) != keys
            or task["version"] != 1
            or task["role"] != "transcription"
            or not re.fullmatch("[a-f0-9]{32}", task["task_id"])
        ):
            raise ValueError("invalid_self_contained_speech_task")
        if (
            type(task["chunk_frames"]) is not int
            or not 0 < task["chunk_frames"] <= 60 * 16000
        ):
            raise ValueError("invalid_provider_chunk_frames")
        if type(task["max_calls"]) is not int or task["max_calls"] < 1:
            raise ValueError("invalid_call_budget")
        path = Path(audio)
        with path.open("rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()
        if (
            sha != task["audio"]["sha256"]
            or path.stat().st_size != task["audio"]["bytes"]
        ):
            raise ValueError("audio_input_mismatch")
        with wave.open(str(path), "rb") as f:
            if (
                f.getnchannels(),
                f.getsampwidth(),
                f.getframerate(),
                f.getcomptype(),
            ) != (1, 2, 16000, "NONE"):
                raise ValueError("normalized_audio_required")
            count = f.getnframes()
            if count <= 0:
                raise ValueError("empty_audio_file")
            duration = validate_projection_clock(
                task["timeline"], policy="packed_projection_v5"
            )
            if round(duration * 16000) != count:
                raise ValueError("audio_clock_frame_count_mismatch")
            folder = self.root / task["task_id"]
            folder.mkdir(exist_ok=True)
            chunks = []
            for index, start in enumerate(range(0, count, task["chunk_frames"])):
                length = min(task["chunk_frames"], count - start)
                raw = f.readframes(length)
                if len(raw) != length * 2:
                    raise ValueError("truncated_pcm_input")
                out = folder / f"{index:06d}.wav"
                memory = io.BytesIO()
                with wave.open(memory, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(raw)
                encoded = memory.getvalue()
                if out.exists():
                    if (
                        hashlib.sha256(out.read_bytes()).digest()
                        != hashlib.sha256(encoded).digest()
                    ):
                        raise ValueError("chunk_cache_mismatch")
                else:
                    out.write_bytes(encoded)
                chunks.append(
                    {
                        "index": index,
                        "start": start,
                        "frames": length,
                        "path": str(out),
                        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                    }
                )
        self.state.ensure(
            task["task_id"], hashlib.sha256(canonical(task)).hexdigest(), task
        )
        return chunks

    def run(self, task, audio):
        with self.state.lock(task["task_id"], "execution"):
            chunks = self.prepare_task(task, audio)
            previous = self.state.task(task["task_id"])
            if previous["status"] == "completed" and not previous["cancelled"]:
                return json.loads(previous["result"])
            value = self.graph.invoke(
                {"task": task, "chunks": chunks, "index": 0, "status": "new"},
                config={
                    "configurable": {"thread_id": task["task_id"]},
                    "recursion_limit": len(chunks) * 5 + 12,
                },
            )
            return value["result"]

    def _prepare(self, s):
        if self.state.cancelled(s["task"]["task_id"]):
            return {"status": "cancelled"}
        return {
            "status": "ready" if len(s["chunks"]) <= s["task"]["max_calls"] else "held"
        }

    def _acquire(self, s):
        task = s["task"]["task_id"]
        if self.state.cancelled(task):
            return {"status": "cancelled"}
        if s["index"] >= len(s["chunks"]):
            return {"status": "completed"}
        chunk = self.state.chunk(task, s["index"])
        if chunk:
            if chunk["status"] == "completed":
                return {"status": "cached"}
            if chunk["status"] == "received":
                return {"status": "received", "reply": json.loads(chunk["reply"])}
            if chunk["status"] == "started":
                self.state.fail(task, s["index"], "interrupted_model_intent", True)
            return {"status": "held"}
        return {"status": "ready"}

    def _invoke(self, s):
        task = s["task"]
        identifier = task["task_id"]
        chunk = s["chunks"][s["index"]]
        with self.state.lock(identifier, "call-fence", shared=True):
            status = self.state.reserve(identifier, s["index"])
            if status == "cancelled":
                return {"status": "cancelled"}
            if status != "reserved":
                return {"status": "held"}
            try:
                raw = Path(chunk["path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != chunk["sha256"]:
                    raise ValueError("chunk_sha_mismatch")
                if self.state.cancelled(identifier):
                    self.state.fail(
                        identifier, s["index"], "cancelled_before_http", False
                    )
                    return {"status": "cancelled"}
                reply = self.model_tool(task["model"], raw, task["source_language"])
                self.state.reply(identifier, s["index"], reply)
                return {"status": "received", "reply": reply}
            except Exception as error:
                self.state.fail(identifier, s["index"], type(error).__name__, True)
                return {"status": "held"}

    def _validate(self, s):
        try:
            chunk = s["chunks"][s["index"]]
            rows = timed_segments(s["reply"], chunk["frames"] / 16000)
            rows = [
                {
                    **row,
                    "start": row["start"] + chunk["start"] / 16000,
                    "end": row["end"] + chunk["start"] / 16000,
                    "id": f"{s['task']['task_id']}:{s['index']}:{i}",
                }
                for i, row in enumerate(rows)
            ]
            self.state.complete(s["task"]["task_id"], s["index"], rows)
            return {"status": "cached"}
        except (ValueError, TypeError, KeyError):
            self.state.fail(
                s["task"]["task_id"], s["index"], "invalid_timed_transcription", False
            )
            return {"status": "held"}

    def _advance(self, s):
        return {"index": s["index"] + 1, "status": "ready"}

    def _terminal(self, s, status, segments=None, projection_trace=None):
        chunks = [
            self.state.chunk(s["task"]["task_id"], i) for i in range(len(s["chunks"]))
        ]
        result = {
            "version": 1,
            "task_id": s["task"]["task_id"],
            "role": "transcription",
            "status": status,
            "completed_chunks": sum(
                bool(c and c["status"] == "completed") for c in chunks
            ),
            "model_calls": self.state.task(s["task"]["task_id"])["calls"],
        }
        if segments is not None:
            result["segments"] = segments
        if projection_trace is not None:
            result["projection_trace"] = projection_trace
        result = self.state.finish(s["task"]["task_id"], result)
        return {"status": result["status"], "result": result}

    def _finish(self, s):
        if self.state.cancelled(s["task"]["task_id"]):
            return self._cancelled(s)
        rows = []
        for i in range(len(s["chunks"])):
            rows.extend(json.loads(self.state.chunk(s["task"]["task_id"], i)["result"]))
        projected, trace = project(
            rows, s["task"]["timeline"], policy="packed_projection_v5"
        )
        return self._terminal(s, "completed", projected, projection_trace=trace)

    def _hold(self, s):
        return self._terminal(s, "held")

    def _cancelled(self, s):
        return self._terminal(s, "cancelled")
