"""Versioned, UI-independent local agent boundary. No queue, provider or GPU startup.

Artifact storage keys are relative to the assigned input/output roots. The caller
owns admission, owner checks, leases and generation fencing before publication.
This runner proves a local execution contract, not durable distributed execution.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Callable

from .node_contracts import node_spec
from .subtitles import segment_subtitles, segments_to_srt
from .transcript import TranscriptSegment

PROTOCOL_VERSION = 1
MAX_INPUT_BYTES = 1024 * 1024
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class AgentCancelled(Exception):
    """Cooperative cancellation; does not imply a remote process was terminated."""


class AgentInputError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def catalog():
    original = node_spec("generate_subtitle")
    return {"protocol_version": PROTOCOL_VERSION, "agents": [{
        "id": original["id"], "revision": "1", "kind": "agent",
        "label": original["label"], "inputs": original["inputs"],
        "outputs": original["outputs"], "runtime": {"device": "cpu", "network": False,
        "provider_calls": False}, "options_schema": {
            "line_width": {"type": "integer", "minimum": 1, "maximum": 120, "default": 42},
            "max_lines": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
        }, "execution": "explicit_local_request", "cancellation": "cooperative",
    }], "remote_transport": False}


def _identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise AgentInputError("Invalid request identity")
    return value


def _artifact(root: Path, reference: dict):
    if (not isinstance(reference, dict) or
            set(reference) != {"storage_key", "type", "bytes", "sha256"} or
            reference["type"] != "transcript" or type(reference["bytes"]) is not int or
            not 0 < reference["bytes"] <= MAX_INPUT_BYTES or
            not isinstance(reference["sha256"], str) or
            not re.fullmatch(r"[a-f0-9]{64}", reference["sha256"])):
        raise AgentInputError("Invalid transcript artifact reference")
    key = reference["storage_key"]
    if (not isinstance(key, str) or not key or "\\" in key or
            any(part in ("", ".", "..") for part in key.split("/")) or Path(key).is_absolute()):
        raise AgentInputError("Invalid artifact storage key")
    root = root.resolve(strict=True)
    path = (root / key).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise AgentInputError("Artifact must remain under its assigned root")
    # Bound the actual read, not only the caller's declared size.
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) != reference["bytes"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise AgentInputError("Artifact size or digest mismatch")
    return raw


def _segments(raw):
    try:
        values = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AgentInputError("Transcript must be UTF-8 JSON") from None
    if not isinstance(values, list) or not 1 <= len(values) <= 10000:
        raise AgentInputError("Transcript must contain 1 to 10000 segments")
    result = []
    for value in values:
        if (not isinstance(value, dict) or set(value) - {"start", "end", "text", "speaker"} or
                not {"start", "end", "text"} <= set(value) or
                any(type(value[k]) not in (int, float) or not math.isfinite(value[k])
                    for k in ("start", "end")) or
                not 0 <= value["start"] < value["end"] or
                not isinstance(value["text"], str) or not 1 <= len(value["text"]) <= 16000 or
                (value.get("speaker") is not None and
                 (not isinstance(value["speaker"], str) or len(value["speaker"]) > 200))):
            raise AgentInputError("Invalid transcript segment")
        result.append(TranscriptSegment.from_dict(value))
    return result


def run(request: dict, input_root: str | Path, output_root: str | Path, *,
        check: Callable[[], None] = lambda: None,
        emit: Callable[[dict], None] = lambda event: None):
    """Execute one immutable attempt. Retry needs a new attempt_id from the caller.

    Completed output is deliberately not adopted on a duplicate request. An
    orchestrator must verify a persisted receipt/input/settings/generation first.
    """
    expected = {"protocol_version", "run_id", "attempt_id", "generation", "agent", "inputs", "options"}
    if not isinstance(request, dict) or set(request) != expected:
        raise AgentInputError("Invalid agent request fields")
    if (type(request["protocol_version"]) is not int or request["protocol_version"] != 1 or
            type(request["generation"]) is not int or request["generation"] < 1 or
            request["agent"] != {"id": "generate_subtitle", "revision": "1"}):
        raise AgentInputError("Unsupported agent protocol, revision or generation")
    run_id, attempt_id = _identity(request["run_id"]), _identity(request["attempt_id"])
    if not isinstance(request["inputs"], dict) or set(request["inputs"]) != {"transcript"}:
        raise AgentInputError("Only the declared transcript input is allowed")
    options = request["options"]
    if not isinstance(options, dict) or set(options) - {"line_width", "max_lines"}:
        raise AgentInputError("Unsupported subtitle options")
    defaults = {"line_width": 42, "max_lines": 2}
    for name, upper in (("line_width", 120), ("max_lines", 4)):
        value = options.get(name, defaults[name])
        if type(value) is not int or not 1 <= value <= upper:
            raise AgentInputError("Invalid subtitle option range")
        defaults[name] = value
    frozen = deepcopy(request)
    request_sha = _digest(frozen)
    check()
    raw = _artifact(Path(input_root), frozen["inputs"]["transcript"])
    segments = _segments(raw)
    base = Path(output_root).resolve(strict=True)
    # Assigned roots are private trusted directories, never arbitrary user paths.
    directory = base / (run_id + "-" + attempt_id)
    if directory.is_symlink():
        raise AgentInputError("Output directory must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=False)
    result = {"protocol_version": 1, "run_id": run_id, "attempt_id": attempt_id,
              "generation": frozen["generation"], "agent": frozen["agent"],
              "request_sha256": request_sha, "status": "running", "outputs": {}}
    def event(status, progress):
        emit({"protocol_version": 1, "run_id": run_id, "attempt_id": attempt_id,
              "generation": frozen["generation"], "status": status, "progress": progress})
    try:
        event("running", 0)
        check()
        output = segments_to_srt(segment_subtitles(segments, **defaults)).encode("utf-8")
        if not output:
            raise AgentInputError("Transcript produced no subtitle cues")
        check()
        # Re-read the original reference to reject a mutation during execution.
        _artifact(Path(input_root), frozen["inputs"]["transcript"])
        if request != frozen:
            raise AgentInputError("Agent request changed during execution")
        target = directory / "subtitles.srt"
        with target.open("xb") as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        result.update(status="completed", outputs={"subtitles": {
            "storage_key": target.relative_to(base).as_posix(), "type": "subtitle",
            "bytes": len(output), "sha256": hashlib.sha256(output).hexdigest()}})
    except AgentCancelled:
        result.update(status="cancelled", error={"code": "cancelled", "retryable": False})
    except (AgentInputError, ValueError):
        result.update(status="failed", error={"code": "invalid_input", "retryable": False})
    except Exception:
        # Do not leak absolute paths, request content, credentials or raw exceptions.
        result.update(status="failed", error={"code": "agent_failed", "retryable": False})
    with (directory / "receipt.json").open("xb") as stream:
        stream.write(_json(result))
        stream.flush()
        os.fsync(stream.fileno())
    event(result["status"], 1 if result["status"] == "completed" else 0)
    return result
