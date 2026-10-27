"""Pure validation only: never classify storage/runtime failures as bad input."""

import json
import re

from video_service.cpu_agents import canonical
from video_service.object_store import validate_reference
from video_service.packed_projection import MAX_BYTES, validate_projection_clock


class InvalidRoleDelivery(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise InvalidRoleDelivery(code)


def fields(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)


def hex_id(value, size):
    return (
        type(value) is str
        and re.fullmatch("[a-f0-9]{" + str(size) + "}", value) is not None
    )


def validate(packet, kind):
    if kind == "cancel_ack":
        fields(
            packet,
            {"version", "role", "task_id", "request_sha256"},
            "invalid_role_cancel_scope",
        )
        require(
            type(packet["version"]) is int
            and packet["version"] == 1
            and packet["role"] == "transcription",
            "invalid_role_cancel_scope",
        )
        require(
            hex_id(packet["task_id"], 32) and hex_id(packet["request_sha256"], 64),
            "invalid_role_cancel_scope",
        )
        return json.loads(canonical(packet))
    require(kind == "result", "invalid_delivery_kind")
    fields(
        packet,
        {"version", "role", "task", "source", "output_owner"},
        "invalid_role_envelope",
    )
    require(
        type(packet["version"]) is int
        and packet["version"] == 1
        and packet["role"] == "transcription",
        "invalid_role_envelope",
    )
    task = packet["task"]
    fields(
        task,
        {
            "version",
            "task_id",
            "role",
            "audio",
            "model",
            "source_language",
            "chunk_frames",
            "max_calls",
            "timeline",
        },
        "invalid_role_task_fields",
    )
    require(
        type(task["version"]) is int
        and task["version"] == 1
        and task["role"] == packet["role"]
        and hex_id(task["task_id"], 32),
        "invalid_role_task_identity",
    )
    fields(task["audio"], {"sha256", "bytes"}, "invalid_role_audio")
    require(
        hex_id(task["audio"]["sha256"], 64)
        and type(task["audio"]["bytes"]) is int
        and task["audio"]["bytes"] > 0,
        "invalid_role_audio",
    )
    fields(task["model"], {"model_id", "revision"}, "invalid_role_model")
    require(
        hex_id(task["model"]["model_id"], 32)
        and type(task["model"]["revision"]) is int
        and task["model"]["revision"] > 0,
        "invalid_role_model",
    )
    require(
        type(task["source_language"]) is str
        and re.fullmatch("auto|[a-z]{2,3}", task["source_language"]) is not None,
        "invalid_source_language",
    )
    require(
        type(task["chunk_frames"]) is int and 0 < task["chunk_frames"] <= 960000,
        "invalid_provider_chunk_frames",
    )
    require(
        type(task["max_calls"]) is int and task["max_calls"] > 0, "invalid_call_budget"
    )
    try:
        validate_projection_clock(task["timeline"], policy="packed_projection_v5")
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise InvalidRoleDelivery("invalid_role_clock") from None
    source = packet["source"]
    fields(source, {"owner", "reference"}, "invalid_artifact_scope")
    require(
        hex_id(source["owner"], 32) and hex_id(packet["output_owner"], 32),
        "invalid_artifact_scope",
    )
    try:
        validate_reference(source["reference"])
    except (ValueError, TypeError, KeyError):
        raise InvalidRoleDelivery("invalid_artifact_reference") from None
    require(
        all(
            task["audio"][key] == source["reference"][key]
            for key in ["sha256", "bytes"]
        ),
        "role_input_reference_mismatch",
    )
    return json.loads(canonical(packet))


def decode(body, kind):
    require(
        type(body) in {bytes, str} and len(body) <= MAX_BYTES, "invalid_role_json_size"
    )

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate_role_json_key")
            value[key] = item
        return value

    def constant(value):
        raise InvalidRoleDelivery("nonfinite_role_json")

    try:
        packet = json.loads(body, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise InvalidRoleDelivery("invalid_role_json") from None
    return validate(packet, kind)
