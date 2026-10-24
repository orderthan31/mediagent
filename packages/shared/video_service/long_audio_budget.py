"""Opt-in long CPU/audio pipeline budgets. Storage permission is NOT execution permission."""

from copy import deepcopy

ID = "audio_long_v5"
RATE = 16000
SECONDS = 6 * 60 * 60
FRAMES = RATE * SECONDS
PCM_BYTES = 1024 * 1024 * 1024
JSON_BYTES = 16 * 1024 * 1024
REGION_BYTES = 131072
CPU_ROLES = {"extract_audio", "preprocess_audio", "generate_subtitle"}
ROLES = CPU_ROLES | {"transcribe", "translate", "review"}


def role_budget(role):
    inputs = {
        "extract_audio": {"video": 256 * 1024 * 1024},
        "preprocess_audio": {"audio": PCM_BYTES, "regions": REGION_BYTES},
        "transcribe": {"audio": PCM_BYTES, "timeline": JSON_BYTES},
        "translate": {"transcript": JSON_BYTES},
        "generate_subtitle": {"transcript": JSON_BYTES},
        "review": {"value": PCM_BYTES},
    }
    outputs = {
        "extract_audio": {"audio": PCM_BYTES},
        "preprocess_audio": {"audio": PCM_BYTES, "timeline": JSON_BYTES},
        "transcribe": {"transcript": JSON_BYTES, "trace": JSON_BYTES},
        "translate": {"transcript": JSON_BYTES},
        "generate_subtitle": {"subtitles": JSON_BYTES, "sami": JSON_BYTES},
        "review": {"value": PCM_BYTES, "regions": REGION_BYTES},
    }
    if role not in ROLES:
        raise ValueError("unsupported_long_audio_role")
    value = {
        "profile": ID,
        "role": role,
        "inputs": deepcopy(inputs[role]),
        "outputs": deepcopy(outputs[role]),
        "source_max_frames": FRAMES,
        "packed_max_frames": FRAMES,
        "process_seconds": 7200,
        "command_seconds": 7200 if role in {"transcribe", "translate"} else 9000,
        "lease_seconds": 7200 if role in {"transcribe", "translate"} else 9600,
        "cache_bytes": (
            6 * 1024 * 1024 * 1024
            if role in {"extract_audio", "preprocess_audio"}
            else 3 * 1024 * 1024 * 1024
            if role == "transcribe"
            else 2 * 1024 * 1024 * 1024
            if role == "review"
            else 64 * 1024 * 1024
        ),
    }

    if role == "review":
        for key in ["process_seconds", "command_seconds", "lease_seconds"]:
            value.pop(key)
        value["human_wait"] = "explicit_confirmation_no_worker_lease"
    return value


def policy():
    return {
        "id": ID,
        "version": 5,
        "original_storage_bytes": 4 * 1024 * 1024 * 1024,
        "pipeline_video_input_bytes": 256 * 1024 * 1024,
        "source_max_frames": FRAMES,
        "packed_max_frames": FRAMES,
        "max_transcript_rows": 10000,
        "transcript_bytes": JSON_BYTES,
        "trace_bytes": JSON_BYTES,
        "roles": {role: role_budget(role) for role in sorted(ROLES)},
        "legacy_roles": {
            role: {
                "input_bytes": 256 * 1024 * 1024,
                "output_bytes": 256 * 1024 * 1024,
                "process_seconds": 60,
                "command_seconds": 90,
                "lease_seconds": 120,
            }
            for role in ["analyze", "encode", "validate_video"]
        },
    }


def definition_policy(definition):
    nodes = definition.get("nodes", [])
    if not any(
        n.get("options", {}).get("media_budget") == ID
        or n.get("options", {}).get("review_kind") == "audio_regions_long_v5"
        for n in nodes
    ):
        return None
    for node in nodes:
        role, options = node["type"], node.get("options", {})
        if (
            role in {"analyze", "encode", "validate_video"}
            and options.get("media_budget", "legacy") == "legacy"
        ):
            continue
        if role not in ROLES:
            raise ValueError("long_audio_role_budget_not_implemented")
        if role == "review":
            kind = options.get("review_kind", "approve_only")
            if (
                kind == "audio_regions_long_v5"
                and options.get("data_type") == "audio"
                or kind == "approve_only"
            ):
                continue
            raise ValueError("long_audio_requires_explicit_audio_review")
        if options.get("media_budget") != ID:
            raise ValueError("mixed_legacy_long_audio_budget")
        if role == "preprocess_audio" and (
            options.get("processing_profile") != "regions_long_v5"
            or options.get("vad_mode", "off") != "off"
        ):
            raise ValueError("long_cpu_profile_must_be_explicit")
        if role in {"transcribe", "translate"}:
            expected = (
                "bounded_60s_v1" if role == "transcribe" else "bounded_100x16k_v1"
            )
            if (
                options.get("batch_policy") != expected
                or "max_model_calls" not in options
            ):
                raise ValueError("long_audio_requires_explicit_batched_model_budget")
        if (
            role == "transcribe"
            and options.get("clock_policy") != "packed_projection_v5"
        ):
            raise ValueError("long_audio_requires_projection_v5")
        if role == "generate_subtitle" and options.get("format") not in {
            "srt",
            "srt_smi",
        }:
            raise ValueError("long_subtitle_profile_requires_explicit_exports")
    return policy()


def command_budget(role, options):
    result = role_budget(role)
    if role in {"transcribe", "translate"}:
        from .cpu_input_policy import model_runtime_seconds

        value = options.get("max_model_calls")
        if not isinstance(value, str) or not value.isdecimal():
            raise ValueError("explicit_model_call_cap_required")
        cap = int(value)
        deadline = model_runtime_seconds(cap)
        result.update(
            max_model_calls=cap,
            process_seconds=deadline,
            command_seconds=deadline,
            lease_seconds=deadline,
        )
    return result


def validate_command(command):
    role = command["agent"]["id"]
    selected = command.get("options", {}).get("media_budget") == ID
    if not selected:
        if (
            command.get("resource_budget") is not None
            or command.get("protocol_version", 1) == 1
            and command["agent"].get("revision") == "5"
            and role in CPU_ROLES
        ):
            raise ValueError("long_audio_budget_not_selected")
        return None
    if command.get("protocol_version", 1) != 1:
        raise ValueError("cpu_long_budget_cannot_authorize_engine_protocol")
    expected = command_budget(role, command["options"])
    if command.get("resource_budget") != expected or (
        role in CPU_ROLES and command["agent"].get("revision") != "5"
    ):
        raise ValueError("frozen_long_audio_budget_mismatch")
    if role in {"transcribe", "translate"}:
        kind = "transcription" if role == "transcribe" else "translation"
        config = command.get(kind, {})
        if (
            config.get("max_model_calls") != expected["max_model_calls"]
            or config.get("max_runtime_seconds") != expected["lease_seconds"]
        ):
            raise ValueError("model_deadline_not_frozen_in_role_budget")
    return expected


def make_clock(spans, *, source_sha256, audio_sha256, source_frames, packed_frames):
    from .cpu_agents import canonical, digest

    value = {
        "version": 5,
        "source_sha256": source_sha256,
        "audio_sha256": audio_sha256,
        "source_frames": source_frames,
        "packed_frames": packed_frames,
        "policy_sha256": digest(policy()),
        "spans": spans,
    }
    read_clock(value, audio_sha256=audio_sha256)
    if len(canonical(value)) > JSON_BYTES:
        raise ValueError("long_clock_serialized_budget_exceeded")
    return value


def read_clock(value, *, audio_sha256):
    import re

    from .audio_clock import validate_clock
    from .cpu_agents import canonical, digest

    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "source_sha256",
            "audio_sha256",
            "source_frames",
            "packed_frames",
            "policy_sha256",
            "spans",
        }
        or type(value["version"]) is not int
        or value["version"] != 5
        or value["audio_sha256"] != audio_sha256
        or any(
            not isinstance(value[key], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value[key])
            for key in ["source_sha256", "audio_sha256"]
        )
        or value["policy_sha256"] != digest(policy())
        or len(canonical(value)) > JSON_BYTES
        or any(
            type(value[key]) is not int or not 0 < value[key] <= FRAMES
            for key in ["source_frames", "packed_frames"]
        )
    ):
        raise ValueError("invalid_long_clock_contract_or_audio_pin")
    spans = value["spans"]
    validate_clock(spans, max_packed_seconds=SECONDS)
    previous = 0
    for span in spans:
        if any(
            abs(number * RATE - round(number * RATE)) > 1e-6 for number in span.values()
        ):
            raise ValueError("long_clock_requires_exact_pcm_frames")
        first, last, start, stop = [
            round(span[key] * RATE)
            for key in ["source_start", "source_end", "packed_start", "packed_end"]
        ]
        if (
            start != previous
            or last - first != stop - start
            or last > value["source_frames"]
        ):
            raise ValueError("long_clock_frame_coverage_mismatch")
        previous = stop
    if previous != value["packed_frames"]:
        raise ValueError("long_clock_packed_frames_mismatch")
    return spans
