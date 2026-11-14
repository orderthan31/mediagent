"""Private, source-frozen ASR/MT recovery. No I/O, cache, or provider access.

Only v2 tasks are supported. Callers must supply durable call rows and verified
source bytes/rows, retain this manifest privately, and enforce authorization and
source immutability outside this module. Hashes detect changes, not forgery.
"""

import hashlib
import json
from copy import deepcopy

from .audio_contract import timed_segments
from .canonical import canonical, digest
from .packed_projection import project
from .role_policy import is_v2, validate_predecessors
from .role_receipts import speech_chunks
from .role_task_contracts import hex_id, validate_models, validate_translation_task
from .transcript_batches import split_transcript
from .translation_output import decode_output, validate_output

_ACTIONS = ["retry", "skip", "manual"]


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _ranges(task, start, end):
    result = []
    for index, span in enumerate(task["timeline"]):
        left, right = max(start, span["packed_start"]), min(end, span["packed_end"])
        if left < right:
            result.append(dict(span_index=index, packed_start=left, packed_end=right,
                               source_start=span["source_start"] + left - span["packed_start"],
                               source_end=span["source_start"] + right - span["packed_start"]))
    return result


def _response(role, unit, value):
    if role == "transcription":
        return timed_segments(value, unit["end"] - unit["start"])
    return decode_output(value, unit["source_rows"])


def build_manifest(task, source, calls):
    """Reconstruct all expected units from persisted evidence without side effects.

    Global source/task/scope/cap errors raise ValueError. A malformed receipt
    within an identifiable unit yields evidence_invalid, never retry permission.
    Returned rows and source_rows contain private transcript text.
    """
    _require(type(task) is dict and is_v2(task), "unit_recovery_legacy_unsupported")
    task = deepcopy(task)
    role = task.get("role")
    _require(role in {"transcription", "translation"}, "unit_recovery_role_unsupported")
    validate_models(task["models"])
    _require(hex_id(task.get("task_id"), 32), "unit_recovery_task_identity")
    _require(type(task.get("max_calls")) is int and task["max_calls"] >= 0, "unit_recovery_call_cap")
    if role == "transcription":
        _require(type(source) is bytes, "unit_recovery_audio_bytes_required")
        _require(type(task.get("chunk_frames")) is int and 0 < task["chunk_frames"] <= 960000,
                 "unit_recovery_chunk_frames")
        chunks = speech_chunks(task, source)
        source_sha = hashlib.sha256(source).hexdigest()
        units = [dict(index=c.chunk_index, input_sha256=c.sha256, start=c.start, end=c.end,
                      source_rows=[], source_ranges=_ranges(task, c.start, c.end)) for c in chunks]
    else:
        validate_translation_task(task)
        raw = canonical(source)
        source_sha = hashlib.sha256(raw).hexdigest()
        _require(task["transcript"] == {"sha256": source_sha, "bytes": len(raw)},
                 "unit_recovery_transcript_binding_changed")
        batches = list(split_transcript(source, policy_version=2))
        units = [dict(index=b.chunk_index, input_sha256=b.sha256, start=b.start, end=b.end,
                      source_rows=deepcopy(b.segments),
                      source_ranges=[{k: r[k] for k in ("id", "start", "end", "speaker") if k in r}
                                     for r in b.segments]) for b in batches]
    _require(type(calls) is list, "unit_recovery_calls_required")
    width = len(task["models"])
    indices = [c.get("chunk_index") for c in calls if type(c) is dict]
    _require(len(indices) == len(calls) and len(calls) <= task["max_calls"]
             and all(type(i) is int and 0 <= i < len(units) * width for i in indices)
             and len(set(indices)) == len(indices), "unit_recovery_receipt_budget_or_scope_changed")
    for unit in units:
        history = sorted([c for c in calls if c["chunk_index"] // width == unit["index"]],
                         key=lambda c: c["chunk_index"])
        unit.update(status="unattempted", error_code=None, rows=[], attempts=[])
        try:
            for position, receipt in enumerate(history):
                candidate = receipt["chunk_index"] % width
                _require(receipt.get("task_id", task["task_id"]) == task["task_id"], "unit_recovery_receipt_task_changed")
                _require(receipt.get("input_sha256") == unit["input_sha256"]
                         and canonical(receipt.get("model")) == canonical(task["models"][candidate]),
                         "unit_recovery_receipt_binding_changed")
                validate_predecessors(history[:position], unit["index"], candidate,
                                      task["models"], unit["input_sha256"])
                status = receipt.get("status")
                _require(status in {"completed", "failed", "started", "unknown"}, "unit_recovery_receipt_status")
                unit["attempts"].append(dict(candidate_index=candidate, model=deepcopy(receipt["model"]),
                                              status=status, error_code=receipt.get("error_code")))
                if status == "completed":
                    unit["rows"] = _response(role, unit, receipt.get("response"))
                    unit.update(status="succeeded", candidate_index=candidate, error_code=None)
                elif status == "failed":
                    _require(type(receipt.get("error_code")) is str and bool(receipt["error_code"]),
                             "unit_recovery_missing_failure_code")
                    unit.update(status="failed", error_code=receipt["error_code"])
                else:
                    unit.update(status="active" if status == "started" else "unknown",
                                error_code=receipt.get("error_code"))
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            unit.update(status="evidence_invalid", error_code="unit_recovery_invalid_receipt_evidence", rows=[])
        unit["allowed_actions"] = list(_ACTIONS) if unit["status"] in {"failed", "unattempted"} else []
    manifest = dict(version=1, role=role, task=task, source_sha256=source_sha, units=units)
    manifest["manifest_sha256"] = digest(manifest)
    return json.loads(canonical(manifest))


def _check_manifest(manifest):
    _require(type(manifest) is dict and manifest.get("version") == 1
             and manifest.get("manifest_sha256") == digest({k: v for k, v in manifest.items() if k != "manifest_sha256"}),
             "unit_recovery_manifest_changed")


def _manual(manifest, unit, value):
    if manifest["role"] == "translation":
        return deepcopy(validate_output(value, unit["source_rows"], batch=True))
    _require(type(value) is list and all(type(r) is dict and not set(r) - {"start", "end", "text", "speaker"}
                                       for r in value), "unit_recovery_manual_fields")
    return timed_segments(value, unit["end"] - unit["start"])


def preview_decisions(manifest, decisions):
    """Validate a partial draft; ready requires every nonsuccess to be resolved.

    execution_units are private unit dictionaries plus candidate_index/model.
    models is the deduplicated frozen binding list; cap is exactly retry count.
    Invalid decisions produce blocked_reasons; a changed manifest raises ValueError.
    """
    _check_manifest(manifest)
    blocked, warnings, normalized, execution, retained, models = [], [], [], [], [], []
    units = manifest["units"]
    seen = set()
    if type(decisions) is not list:
        decisions = []
        blocked.append("unit_recovery_decisions_required")
    for decision in decisions:
        try:
            _require(type(decision) is dict and not set(decision) - {"unit_index", "action", "candidate_index", "value"},
                     "unit_recovery_decision_fields")
            index = decision.get("unit_index")
            _require(type(index) is int and 0 <= index < len(units) and index not in seen,
                     "unit_recovery_decision_index")
            seen.add(index)
            unit, action = units[index], decision.get("action")
            _require(action in unit["allowed_actions"], "unit_recovery_action_blocked")
            item = dict(unit_index=index, action=action)
            if action == "retry":
                candidate = decision.get("candidate_index", 0)
                _require("value" not in decision and type(candidate) is int
                         and 0 <= candidate < len(manifest["task"]["models"]), "unit_recovery_retry_candidate")
                model = deepcopy(manifest["task"]["models"][candidate])
                item["candidate_index"] = candidate
                execution.append({**deepcopy(unit), "candidate_index": candidate, "model": model})
                if model not in models:
                    models.append(model)
            elif action == "manual":
                _require("candidate_index" not in decision, "unit_recovery_manual_candidate")
                item["value"] = _manual(manifest, unit, decision.get("value"))
                retained.append({**deepcopy(unit), "rows": deepcopy(item["value"]), "provenance": "manual"})
            else:
                _require(not {"candidate_index", "value"} & set(decision), "unit_recovery_skip_fields")
                warnings.append(f"unit:{index}:omitted_from_output")
            normalized.append(item)
        except (ValueError, TypeError, KeyError, IndexError) as error:
            blocked.append(str(error))
    for unit in units:
        if unit["status"] == "succeeded":
            retained.append({**deepcopy(unit), "provenance": "reused"})
        elif unit["status"] in {"unknown", "active", "evidence_invalid"}:
            blocked.append(f"unit:{unit['index']}:{unit['status']}")
        elif unit["index"] not in seen:
            blocked.append(f"unit:{unit['index']}:unresolved")
    if not units or (not execution and not any(u["rows"] for u in retained)):
        blocked.append("unit_recovery_empty_output_unsupported")
    return dict(decisions=sorted(normalized, key=lambda d: d["unit_index"]),
                retained_units=sorted(retained, key=lambda u: u["index"]),
                execution_units=sorted(execution, key=lambda u: u["index"]),
                additional_call_limit=len(execution), models=models, warnings=warnings,
                blocked_reasons=blocked, ready=not blocked)


def assemble_resolutions(manifest, decisions, retry_results=None):
    """Assemble private output; retry_results maps str(unit index) to raw response.

    Requires an exact result-key set, with no synthetic receipts or hidden retry.
    Skip omits entire units for both roles; empty final output is unsupported.
    """
    preview = preview_decisions(manifest, decisions)
    _require(preview["ready"], ";".join(preview["blocked_reasons"]))
    retry_results = {} if retry_results is None else retry_results
    expected = {str(u["index"]) for u in preview["execution_units"]}
    _require(type(retry_results) is dict and set(retry_results) == expected, "unit_recovery_retry_result_scope")
    chosen = {d["unit_index"]: d for d in preview["decisions"]}
    rows, kept_source, omitted_source, resolutions = [], [], [], []
    counts = dict(reused=0, model_retry=0, manual=0, skipped=0)
    for unit in manifest["units"]:
        index = unit["index"]
        decision = chosen.get(index)
        if unit["status"] == "succeeded":
            provenance, value = "reused", deepcopy(unit["rows"])
        elif decision["action"] == "skip":
            provenance, value = "skipped", []
        elif decision["action"] == "manual":
            provenance, value = "manual", _manual(manifest, unit, decision["value"])
        else:
            provenance = "model_retry"
            value = _response(manifest["role"], unit, retry_results[str(index)])
        counts[provenance] += 1
        entry = dict(unit_index=index, provenance=provenance, input_sha256=unit["input_sha256"],
                     source_ranges=deepcopy(unit["source_ranges"]), output_row_count=len(value))
        if provenance == "model_retry":
            candidate = decision["candidate_index"]
            entry.update(candidate_index=candidate, model=deepcopy(manifest["task"]["models"][candidate]))
        if provenance == "skipped":
            entry["omitted_ids"] = [r["id"] for r in unit["source_rows"] if "id" in r]
            omitted_source.extend(unit["source_rows"])
        else:
            kept_source.extend(unit["source_rows"])
        if manifest["role"] == "transcription":
            value = [{**r, "start": r["start"] + unit["start"], "end": r["end"] + unit["start"],
                      "id": f"{manifest['task']['task_id']}:{index}:{position}"} for position, r in enumerate(value)]
        rows.extend(value)
        resolutions.append(entry)
    _require(bool(rows), "unit_recovery_empty_output_unsupported")
    if manifest["role"] == "transcription":
        segments, trace = project(rows, manifest["task"]["timeline"], policy="packed_projection_v5")
        # Policy 5's clock intersections/text mapping remain unchanged. Its
        # aggregate-content-derived split IDs are not stable under omission, so
        # recovery IDs use the original task/chunk/row and original piece index.
        trace["recovery_id_policy"] = "root_task_chunk_row_piece_v1"
        for entry in trace["rows"]:
            if len(entry["pieces"]) > 1:
                for piece_index, piece in enumerate(entry["pieces"]):
                    if piece["status"] == "emitted":
                        identifier = f"{entry['packed_segment']['id']}:piece:{piece_index}"
                        segments[piece["output_index"]]["id"] = identifier
                        piece["output_id"] = identifier
        trace["output_transcript_sha256"] = digest(segments)
        _require(bool(segments), "unit_recovery_empty_output_unsupported")
        packed = rows
    else:
        original = [r for u in manifest["units"] for r in u["source_rows"]]
        _require(digest(original) == manifest["source_sha256"] and len(kept_source) + len(omitted_source) == len(original),
                 "unit_recovery_source_partition_changed")
        validate_output(rows, kept_source)
        segments, packed, trace = rows, [], None
    resolution = dict(version=1, role=manifest["role"], manifest_sha256=manifest["manifest_sha256"],
                      source_sha256=manifest["source_sha256"], units=resolutions, counts=counts,
                      additional_call_limit=preview["additional_call_limit"],
                      output_sha256=digest(segments))
    return deepcopy(dict(segments=segments, packed_segments=packed, projection_trace=trace,
                         resolution_manifest=resolution))
