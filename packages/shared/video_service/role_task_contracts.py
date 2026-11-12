"""Pure validation only: never classify storage/runtime failures as bad input."""

import json
import re

from video_service.canonical import canonical
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


def validate(packet, kind, *, expected_role=None):
    if expected_role is not None:
        require(packet.get("role") == expected_role, "wrong_role_delivery")
    if kind == "cancel_ack":
        fields(
            packet,
            {"version", "role", "task_id", "request_sha256"},
            "invalid_role_cancel_scope",
        )
        require(
            type(packet["version"]) is int
            and packet["version"] == 1
            and packet["role"] in {"transcription", "translation", "vocalization"},
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
        and packet["role"] in {"transcription", "translation", "vocalization"},
        "invalid_role_envelope",
    )
    task = packet["task"]
    if packet["role"] == "vocalization":
        validate_vocal_task(task)
    elif packet["role"] == "translation":
        validate_translation_task(task)
    else:
        from video_service.role_policy import is_v2

        v2 = is_v2(task)
        fields(
            task,
            {
                "version",
                "task_id",
                "role",
                "audio",
                "source_language",
                "chunk_frames",
                "max_calls",
                "timeline",
            } | ({"models", "role_policy_version"} if v2 else {"model"}),
            "invalid_role_task_fields",
        )
        require(
            type(task["version"]) is int
            and task["version"] == (2 if v2 else 1)
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
        if v2:
            validate_models(task["models"])
        else:
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
            type(task["max_calls"]) is int and task["max_calls"] > 0,
            "invalid_call_budget",
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
            task["transcript" if packet["role"] == "translation" else "audio"][key]
            == source["reference"][key]
            for key in ["sha256", "bytes"]
        ),
        "role_input_reference_mismatch",
    )
    return json.loads(canonical(packet))


def decode(body, kind, *, expected_role=None):
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
    return validate(packet, kind, expected_role=expected_role)


def validate_translation_task(task):
    from video_service.role_policy import is_v2

    v2 = is_v2(task)
    if "translation_context" in task:
        require(v2, "translation_reference_requires_role_policy_v2")
        from .translation_context import validate as validate_context
        try:
            validate_context(task["translation_context"])
        except (ValueError, TypeError, KeyError):
            raise InvalidRoleDelivery("invalid_translation_reference_context") from None
    fields(
        task,
        {
            "version",
            "task_id",
            "role",
            "transcript",
            "models",
            "source_language",
            "target_language",
            "batch_policy",
            "max_calls",
        } | ({"role_policy_version"} if v2 else set()) | ({"translation_context"} if "translation_context" in task else set()),
        "invalid_translation_task",
    )
    require(
        type(task["version"]) is int
        and task["version"] == (2 if v2 else 1)
        and task["role"] == "translation"
        and hex_id(task["task_id"], 32),
        "invalid_translation_identity",
    )
    fields(task["transcript"], {"sha256", "bytes"}, "invalid_transcript_reference")
    require(
        hex_id(task["transcript"]["sha256"], 64)
        and type(task["transcript"]["bytes"]) is int
        and 0 < task["transcript"]["bytes"] <= 16 * 1024 * 1024,
        "invalid_transcript_reference",
    )
    require(
        type(task["models"]) is list and 1 <= len(task["models"]) <= 4,
        "invalid_translation_candidates",
    )
    for model in task["models"]:
        fields(model, {"model_id", "revision"} | ({"pin_sha256"} if v2 else set()), "invalid_translation_model")
        require(
            hex_id(model["model_id"], 32)
            and type(model["revision"]) is int
            and model["revision"] > 0,
            "invalid_translation_model",
        )
        if v2:
            require(hex_id(model["pin_sha256"], 64), "invalid_translation_model_pin")
    require(
        len({m["model_id"] for m in task["models"]}) == len(task["models"]),
        "duplicate_translation_model",
    )
    require(
        type(task["max_calls"]) is int
        and task["max_calls"] > 0
        and task["batch_policy"] in {"single_100x16k_v1", "bounded_100x16k_v1"},
        "invalid_translation_budget",
    )
    from video_service.translation_languages import languages

    try:
        languages(task["source_language"], task["target_language"])
    except (ValueError, TypeError):
        raise InvalidRoleDelivery("invalid_translation_languages") from None
    return task


def validate_models(models):
    require(type(models) is list and 1 <= len(models) <= 4, "invalid_role_candidates")
    for model in models:
        fields(model, {"model_id", "revision", "pin_sha256"}, "invalid_role_model")
        require(
            hex_id(model["model_id"], 32)
            and type(model["revision"]) is int and model["revision"] > 0
            and hex_id(model["pin_sha256"], 64),
            "invalid_role_model",
        )
    require(len({m["model_id"] for m in models}) == len(models), "duplicate_role_model")


def validate_vocal_task(task):
    streamed = task.get("batch_policy") == "streamed_vocalization_v2"
    fields(
        task,
        {
            "version",
            "task_id",
            "role",
            "audio",
            "models",
            "source_language",
            "purpose",
            "strength",
            "binding_sha256",
            "max_calls",
        }
        | ({"batch_policy"} if streamed else set()),
        "invalid_vocal_task",
    )
    require(
        type(task["version"]) is int
        and task["version"] == (2 if streamed else 1)
        and task["role"] == "vocalization"
        and hex_id(task["task_id"], 32),
        "invalid_vocal_identity",
    )
    fields(task["audio"], {"sha256", "bytes"}, "invalid_vocal_audio")
    require(
        hex_id(task["audio"]["sha256"], 64)
        and type(task["audio"]["bytes"]) is int
        and 0
        < task["audio"]["bytes"]
        <= (1024 * 1024 * 1024 if streamed else 300 * 32000 + 65536),
        "invalid_vocal_audio",
    )
    require(
        type(task["models"]) is list and 1 <= len(task["models"]) <= 4,
        "invalid_vocal_models",
    )
    for model in task["models"]:
        fields(model, {"model_id", "revision"}, "invalid_vocal_model")
        require(
            hex_id(model["model_id"], 32)
            and type(model["revision"]) is int
            and model["revision"] > 0,
            "invalid_vocal_model",
        )
    require(
        len({m["model_id"] for m in task["models"]}) == len(task["models"])
        and hex_id(task["binding_sha256"], 64),
        "invalid_vocal_binding",
    )
    require(
        task["purpose"] == "vocalization_regions_v1"
        and task["strength"] in {"off", "conservative", "strong", "silence3"}
        and type(task["source_language"]) is str
        and re.fullmatch("auto|[a-z]{2,3}", task["source_language"])
        and type(task["max_calls"]) is int
        and 1 <= task["max_calls"] <= (4096 if streamed else 128),
        "invalid_vocal_policy",
    )
    return task
