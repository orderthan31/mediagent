"""Deterministic next vocal call from the existing domain protocol and cached answers."""

from .cpu_agents import digest
from .vocalization_proposals import analyze


class _NeedCall(Exception):
    def __init__(self, context, clips, schema):
        self.context, self.clips, self.schema = context, clips, schema


def vocal_plan(raw, task, completed, cancelled=lambda: False):
    def invoke(context, clips, schema):
        found, reply = completed(context["call_index"])
        if found:
            return reply
        raise _NeedCall(context, clips, schema)

    try:
        if task.get("batch_policy") == "streamed_vocalization_v2":
            from .vocalization_proposals import analyze_stream

            value = analyze_stream(
                raw,
                source_sha256=task["audio"]["sha256"],
                language=task["source_language"],
                strength=task["strength"],
                binding_sha256=task["binding_sha256"],
                max_calls=task["max_calls"],
                invoke=invoke,
                cancelled=cancelled,
            )
        else:
            value = analyze(
                raw,
                language=task["source_language"],
                strength=task["strength"],
                binding_sha256=task["binding_sha256"],
                max_calls=task["max_calls"],
                invoke=invoke,
                cancelled=cancelled,
            )
    except _NeedCall as call:
        return {
            "pending": {
                "context": call.context,
                "schema": call.schema,
                "input_sha256": digest(
                    {"context": call.context, "schema": call.schema}
                ),
            },
            "clips": call.clips,
        }
    return {"document": value["document"], "contexts": value["request_contexts"]}
