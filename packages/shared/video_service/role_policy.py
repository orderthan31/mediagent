"""Explicit frozen role policy. Missing or non-integer versions stay legacy."""

from .canonical import canonical, digest

ADVANCE = frozenset({"rate_limited", "upstream_failure", "invalid_response", "unavailable"})


def snapshot_version(snapshot):
    value = snapshot.get("role_policy_version")
    return 2 if type(value) is int and value == 2 else 1


def is_v2(task):
    return (
        type(task.get("version")) is int
        and task["version"] == 2
        and type(task.get("role_policy_version")) is int
        and task["role_policy_version"] == 2
    )


def model_binding(pin):
    return {
        "model_id": pin["model_id"],
        "revision": pin["revision"],
        "pin_sha256": digest(pin),
    }


def tool_context(task):
    if not is_v2(task):
        return {}
    result = {"version": 2, "role_policy_version": 2, "task_sha256": digest(task)}
    if "translation_context" in task:
        from .translation_context import validate
        if task.get("role") != "translation":
            raise ValueError("translation_context_wrong_role")
        validate(task["translation_context"])
        result["translation_context_version"] = 1
    return result


def endpoint_error_code(error, *, v2=False):
    # Keep the historical adapter error code intact; only the explicit role v2
    # context distinguishes finite output capacity from an eligible bad response.
    if v2 and getattr(error, "capacity_exceeded", False):
        return "output_capacity_exceeded"
    return error.code


def attempt_index(chunk, candidate, width):
    if any(type(v) is not int for v in (chunk, candidate, width)) or chunk < 0 or not 0 <= candidate < width <= 4:
        raise ValueError("invalid_role_attempt_index")
    return chunk * width + candidate


def validate_predecessors(history, chunk, candidate, models, source_sha):
    """Caller holds the task advisory transaction lock through intent commit.

    Only a complete prefix of definitive failures permits a NEW intent. Existing
    completed/started/unknown attempts cannot be bypassed, even by a lower index.
    """
    width = len(models)
    base = attempt_index(chunk, 0, width)
    relevant = {r["chunk_index"]: r for r in history if base <= r["chunk_index"] < base + width}
    if set(relevant) != set(range(base, base + candidate)):
        raise ValueError("tool_candidate_predecessor_not_definitively_failed")
    for offset in range(candidate):
        row = relevant[base + offset]
        if row["status"] != "failed" or row["error_code"] not in ADVANCE:
            raise ValueError("tool_candidate_predecessor_not_definitively_failed")
        if row["input_sha256"] != source_sha or canonical(row["model"]) != canonical(models[offset]):
            raise ValueError("tool_candidate_predecessor_binding_changed")
