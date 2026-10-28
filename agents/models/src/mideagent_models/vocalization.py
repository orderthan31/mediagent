"""Independent detect/confirm LangGraph with role-local intent/results and no DB keys."""

import hashlib
import json
from pathlib import Path

from video_service.cpu_agents import canonical
from video_service.vocal_role_plan import vocal_plan

from .translation import TranslationAgent


class VocalizationAgent(TranslationAgent):
    role = "vocalization"

    def prepare_task(self, task, path):
        from .protocol import validate_vocal_task

        validate_vocal_task(task)
        streamed = task.get("batch_policy") == "streamed_vocalization_v2"
        with Path(path).open("rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()
        if (
            Path(path).stat().st_size != task["audio"]["bytes"]
            or sha != task["audio"]["sha256"]
        ):
            raise ValueError("audio_input_mismatch")
        vocal_plan(
            Path(path) if streamed else Path(path).read_bytes(),
            task,
            lambda _: (False, None),
        )
        self.state.ensure(
            task["task_id"], hashlib.sha256(canonical(task)).hexdigest(), task
        )

    def run(self, task, path):
        with self.state.lock(task["task_id"], "execution"):
            self.prepare_task(task, path)
            prior = self.state.task(task["task_id"])
            if prior["status"] == "completed" and not prior["cancelled"]:
                return json.loads(prior["result"])
            return self.graph.invoke(
                {"task": task, "audio_path": str(path), "batch": 0, "status": "new"},
                config={
                    "configurable": {"thread_id": task["task_id"]},
                    "recursion_limit": task["max_calls"] * 7 + 16,
                },
            )["result"]

    def _prepare(self, s):
        return {
            "status": "cancelled"
            if self.state.cancelled(s["task"]["task_id"])
            else "held"
            if self.state.task(s["task"]["task_id"])["status"] == "held"
            else "ready"
        }

    def _plan(self, s, override=None):
        task = s["task"]

        def completed(call):
            if override and override[0] == call:
                return True, override[1]
            for candidate in range(len(task["models"])):
                row = self.state.chunk(
                    task["task_id"], call * len(task["models"]) + candidate
                )
                if row and row["status"] == "completed":
                    return True, json.loads(row["result"])
            return False, None

        return vocal_plan(
            Path(s["audio_path"])
            if task.get("batch_policy") == "streamed_vocalization_v2"
            else Path(s["audio_path"]).read_bytes(),
            task,
            completed,
            lambda: self.state.cancelled(task["task_id"]),
        )

    def _select(self, s):
        from video_service.postgres.translation import ADVANCE

        task = s["task"]
        identifier = task["task_id"]
        if self.state.cancelled(identifier):
            return {"status": "cancelled"}
        if self.state.task(identifier)["status"] == "held":
            return {"status": "held"}
        try:
            plan = self._plan(s)
        except ValueError:
            return {"status": "held"}
        if "document" in plan:
            return {"status": "completed", "document": plan["document"]}
        pending = plan["pending"]
        call = pending["context"]["call_index"]
        for candidate in range(len(task["models"])):
            index = call * len(task["models"]) + candidate
            row = self.state.chunk(identifier, index)
            selection = {
                "pending": pending,
                "batch": call,
                "candidate": candidate,
                "call_index": index,
            }
            if not row:
                return {**selection, "status": "ready"}
            if row["status"] == "received":
                return {
                    **selection,
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
            status = self.state.reserve(identifier, index)
            if status == "cancelled":
                return {"status": "cancelled"}
            if status != "reserved":
                return {"status": "held"}
            if self.state.cancelled(identifier):
                return {"status": "cancelled"}
            try:
                reply = self.model_tool(task, s["pending"], s["candidate"])
            except Exception as error:
                self.state.fail(identifier, index, type(error).__name__, True)
                return {"status": "held"}
            if reply.get("status") == "received":
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
        try:
            self._plan(s, override=(s["pending"]["context"]["call_index"], s["reply"]))
        except ValueError:
            self.state.candidate_failed(
                s["task"]["task_id"], s["call_index"], "invalid_response"
            )
            return {"status": "retry"}
        self.state.complete(s["task"]["task_id"], s["call_index"], s["reply"])
        return {"status": "cached"}

    def _finish(self, s):
        task = s["task"]
        plan = self._plan(s)
        chunks = []
        for context in plan["contexts"]:
            call = context["call_index"]
            for candidate, model in enumerate(task["models"]):
                row = self.state.chunk(
                    task["task_id"], call * len(task["models"]) + candidate
                )
                if row and row["status"] == "completed":
                    chunks.append(
                        {
                            "call_index": call,
                            "phase": context["phase"],
                            "candidate_index": candidate,
                            "model": model,
                        }
                    )
                    break
        return self._terminal(
            s,
            "completed",
            document=plan["document"],
            chunks=chunks,
            completed_chunks=len(chunks),
            purpose=task["purpose"],
        )
