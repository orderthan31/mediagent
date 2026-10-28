"""Role-scoped processing of verified originals; no global store/legacy limit changes.

The server resolves this contract from the selected original. It is not a user
requirement to select a different file or a special demonstration workflow.
"""

from copy import deepcopy

ID = "original_video_v6"
VIDEO_BYTES = 4 * 1024**3
PCM_BYTES = 1024**3
JSON_BYTES = 16 * 1024**2
SECONDS = 21600
CPU_ROLES = frozenset({"analyze", "extract_audio", "encode", "validate_video"})
CONTROLS = frozenset(
    {
        "review",
        "subtitle_tracks",
        "subtitle_outputs",
        "subtitle_track",
        "select",
        "join",
    }
)


def role_budget(role):
    if role not in CPU_ROLES:
        raise ValueError("unsupported_original_video_role")
    inputs = {
        "analyze": {"video": VIDEO_BYTES},
        "extract_audio": {"video": VIDEO_BYTES},
        "encode": {"video": VIDEO_BYTES, "subtitles": JSON_BYTES},
        "validate_video": {"video": VIDEO_BYTES},
    }
    outputs = {
        "analyze": {"metadata": JSON_BYTES},
        "extract_audio": {"audio": PCM_BYTES},
        "encode": {"video": VIDEO_BYTES},
        "validate_video": {"report": JSON_BYTES},
    }
    return {
        "profile": ID,
        "role": role,
        "inputs": inputs[role],
        "outputs": outputs[role],
        "source_max_frames": 16000 * SECONDS,
        "packed_max_frames": 16000 * SECONDS,
        "process_seconds": 7200,
        "command_seconds": 9000,
        "lease_seconds": 9600,
        "cache_bytes": (10 if role == "encode" else 6) * 1024**3,
    }


def policy():
    from .long_audio_budget import policy as audio_policy

    audio = audio_policy()
    return {
        "id": ID,
        "version": 6,
        "original_storage_bytes": VIDEO_BYTES,
        "pipeline_video_input_bytes": VIDEO_BYTES,
        "max_duration_seconds": SECONDS,
        "max_pixels": 3840 * 2160,
        "roles": {**audio["roles"], **{r: role_budget(r) for r in sorted(CPU_ROLES)}},
        "audio_clock_policy": audio["id"],
        "independent_execution_required": True,
    }


def selected(asset, definition):
    nodes = definition.get("nodes", [])
    if any(n.get("options", {}).get("media_budget") == ID for n in nodes):
        return True
    media = asset.get("metadata", {}).get("media") or {}
    return any(n.get("type") not in {"encode", "validate_video"} for n in nodes) and (
        asset["bytes"] > 268435456 or media.get("duration", 0) > 300
    )


def source_policy(asset, definition):
    from .cpu_input_policy import validate_media
    from .long_audio_budget import ROLES

    if asset.get("metadata", {}).get("registration_state") != "verified":
        raise ValueError("Verified original media required")
    if type(asset["bytes"]) is not int or not 0 < asset["bytes"] <= VIDEO_BYTES:
        raise ValueError("Original video exceeds explicit 4 GiB processing budget")
    validate_media(asset["metadata"].get("media") or {})
    nodes = definition.get("nodes", [])
    if not nodes or any(
        n.get("type") not in CPU_ROLES | ROLES | CONTROLS
        and not (
            n.get("type") == "vocalize"
            and n.get("options", {}).get("batch_policy") == "streamed_vocalization_v2"
        )
        for n in nodes
    ):
        raise ValueError(
            "Selected workflow has an unsupported original-video execution role"
        )
    return policy()


def resolve_definition(asset, definition):
    if not selected(asset, definition):
        return definition
    source_policy(asset, definition)
    result = deepcopy(definition)
    from .long_audio_budget import ID as AUDIO_ID

    for node in result["nodes"]:
        role, options = node["type"], node["options"]
        if role in CPU_ROLES:
            options["media_budget"] = ID
        elif role in {
            "preprocess_audio",
            "transcribe",
            "translate",
            "generate_subtitle",
        }:
            options["media_budget"] = AUDIO_ID
            if role == "preprocess_audio":
                if options.get("vad_mode", "off") != "off":
                    raise ValueError(
                        "Selected NVIDIA mode requires its separately registered long-input engine"
                    )
                options["processing_profile"] = "regions_long_v5"
            elif role == "transcribe":
                options.update(
                    batch_policy="bounded_60s_v1", clock_policy="packed_projection_v5"
                )
            elif role == "translate":
                options["batch_policy"] = "bounded_100x16k_v1"
            elif role == "generate_subtitle":
                options.setdefault("format", "srt")
    return result


def validate_command(command):
    role = command["agent"]["id"]
    expected = role_budget(role)
    if (
        command.get("protocol_version", 1) != 1
        or command["agent"].get("revision") != "6"
        or command.get("options", {}).get("media_budget") != ID
        or command.get("resource_budget") != expected
    ):
        raise ValueError("frozen_original_video_role_budget_mismatch")
    return expected


def extend_schemas(request, response):
    from .node_contracts import node_spec

    for envelope in [request, response]:
        command = envelope["properties"]["command"]
        command["properties"]["agent"]["properties"]["revision"]["enum"].append("6")
        for role in sorted(CPU_ROLES):
            base = next(
                b
                for b in command["oneOf"]
                if b["properties"]["agent"]["properties"]["id"]["const"] == role
                and b["properties"].get("resource_budget") is False
            )
            branch = deepcopy(base)
            branch.pop("allOf", None)
            branch["required"] = ["resource_budget"]
            branch["properties"]["resource_budget"] = {"const": role_budget(role)}
            branch["properties"]["agent"]["properties"]["revision"] = {"const": "6"}
            branch["properties"]["options"].setdefault("required", []).append(
                "media_budget"
            )
            branch["properties"]["options"]["properties"]["media_budget"] = {
                "const": ID
            }
            for port, kind in node_spec(role)["inputs"].items():
                reference = deepcopy(envelope["$defs"]["input_artifact"])
                reference["properties"]["bytes"]["maximum"] = role_budget(role)[
                    "inputs"
                ][port]
                reference["properties"]["type"] = {"const": kind}
                branch["properties"]["inputs"]["properties"][port] = reference
            command["oneOf"].append(branch)
    result = response["properties"]["result"]
    result["properties"]["agent"]["properties"]["revision"]["enum"].append("6")
    branches = []
    for role in sorted(CPU_ROLES):
        outputs = {}
        for port, maximum in role_budget(role)["outputs"].items():
            reference = deepcopy(response["$defs"]["artifact"])
            reference["properties"]["bytes"]["maximum"] = maximum
            reference["properties"]["type"] = {
                "const": node_spec(role)["outputs"][port]
            }
            outputs[port] = reference
        branches.append(
            {
                "properties": {
                    "agent": {"properties": {"id": {"const": role}}},
                    "outputs": {"properties": outputs, "additionalProperties": False},
                },
                "if": {"properties": {"status": {"const": "completed"}}},
                "then": {"properties": {"outputs": {"required": list(outputs)}}},
            }
        )
    previous = result["allOf"]
    result["allOf"] = [
        {
            "if": {
                "properties": {"agent": {"properties": {"revision": {"const": "6"}}}}
            },
            "then": {"oneOf": branches},
            "else": {"allOf": previous},
        }
    ]
