"""Pure v2 receiver reconstruction from durable tool facts; no trusted client choice."""

import hashlib

from .audio_batches import split_normalized_audio
from .audio_contract import timed_segments
from .canonical import canonical
from .packed_projection import validate_projection_clock
from .role_policy import validate_predecessors
from .transcript_batches import split_transcript
from .translation_output import decode_output, validate_output


def speech_chunks(task, raw):
    if len(raw) != task["audio"]["bytes"] or hashlib.sha256(raw).hexdigest() != task["audio"]["sha256"]:
        raise ValueError("role_audio_binding_changed")
    chunks = list(split_normalized_audio(raw, chunk_frames=task["chunk_frames"]))
    duration = validate_projection_clock(task["timeline"], policy="packed_projection_v5")
    if round(duration * 16000) != round(chunks[-1].end * 16000):
        raise ValueError("role_audio_clock_changed")
    return chunks


def _check_calls(task, calls, count):
    width = len(task["models"])
    indices = [c["chunk_index"] for c in calls]
    if len(calls) > task["max_calls"] or len(set(indices)) != len(indices) or any(
        type(index) is not int or not 0 <= index < count * width for index in indices
    ):
        raise ValueError("role_tool_receipt_budget_or_scope_changed")


def _selected(task, calls, chunk, sha):
    width = len(task["models"])
    choices = [c for c in calls if c["chunk_index"] // width == chunk and c["status"] == "completed"]
    if len(choices) != 1:
        raise ValueError("role_tool_completed_receipt_missing_or_ambiguous")
    selected = choices[0]
    candidate = selected["chunk_index"] % width
    if selected["input_sha256"] != sha or canonical(selected["model"]) != canonical(task["models"][candidate]):
        raise ValueError("role_tool_selection_binding_changed")
    validate_predecessors([c for c in calls if c is not selected], chunk, candidate, task["models"], sha)
    return candidate, selected["response"]


def speech_receipts(task, raw, calls):
    chunks = speech_chunks(task, raw)
    _check_calls(task, calls, len(chunks))
    rows, receipts = [], []
    for chunk in chunks:
        candidate, response = _selected(task, calls, chunk.chunk_index, chunk.sha256)
        for index, row in enumerate(timed_segments(response, chunk.end - chunk.start)):
            rows.append({**row, "start": row["start"] + chunk.start, "end": row["end"] + chunk.start,
                         "id": f"{task['task_id']}:{chunk.chunk_index}:{index}"})
        receipts.append({"index": chunk.chunk_index, "start": round(chunk.start * 16000),
                         "frames": round((chunk.end - chunk.start) * 16000), "input_sha256": chunk.sha256,
                         "candidate_index": candidate, "model": task["models"][candidate]})
    return rows, receipts


def translation_receipts(task, source, calls):
    batches = list(split_transcript(source, policy_version=2))
    _check_calls(task, calls, len(batches))
    rows, receipts = [], []
    for batch in batches:
        candidate, response = _selected(task, calls, batch.chunk_index, batch.sha256)
        rows.extend(decode_output(response, batch.segments))
        receipts.append({"index": batch.chunk_index, "start": batch.start, "end": batch.end,
                         "input_sha256": batch.sha256, "candidate_index": candidate,
                         "model": task["models"][candidate]})
    validate_output(rows, source)
    return rows, receipts
