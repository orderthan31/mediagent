"""Role-v5 wire keeps old global artifact bounds and binds exact budget metadata."""

from copy import deepcopy

from jsonschema import Draft202012Validator
from video_service.agent_protocol import schemas
from video_service.long_audio_budget import ID, role_budget


def test_cpu_v5_wire_is_opt_in_and_budget_exact():
    validator = Draft202012Validator(schemas()["agent.command.v1.schema.json"])
    command = {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": "preprocess_audio", "revision": "5"},
        "inputs": {
            "audio": {
                "storage_key": "blobs/" + "c" * 64,
                "sha256": "c" * 64,
                "bytes": 800 * 1024 * 1024,
                "type": "audio",
            }
        },
        "options": {
            "media_budget": ID,
            "processing_profile": "regions_long_v5",
            "vad_mode": "off",
            "audio_filter": "strong",
        },
        "resource_budget": role_budget("preprocess_audio"),
    }
    packet = {"version": 1, "owner": "d" * 32, "command": command}
    assert validator.is_valid(packet), list(validator.iter_errors(packet))
    bad = deepcopy(packet)
    bad["command"]["resource_budget"]["inputs"]["audio"] += 1
    assert not validator.is_valid(bad)
    old = deepcopy(packet)
    old["command"]["agent"]["revision"] = "1"
    assert not validator.is_valid(old)
    missing = deepcopy(packet)
    del missing["command"]["resource_budget"]
    assert not validator.is_valid(missing)


def test_long_result_can_exceed_legacy_bytes_only_in_its_exact_role():
    request = {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": "preprocess_audio", "revision": "5"},
        "inputs": {
            "audio": {
                "storage_key": "blobs/" + "c" * 64,
                "sha256": "c" * 64,
                "bytes": 100,
                "type": "audio",
            }
        },
        "options": {
            "media_budget": ID,
            "processing_profile": "regions_long_v5",
            "vad_mode": "off",
        },
        "resource_budget": role_budget("preprocess_audio"),
    }
    result = {
        k: request[k]
        for k in ["protocol_version", "run_id", "attempt_id", "generation", "agent"]
    }
    result.update(
        request_sha256="e" * 64,
        status="completed",
        transport="s3_subprocess",
        outputs={
            "audio": {
                "storage_key": "blobs/" + "f" * 64,
                "sha256": "f" * 64,
                "bytes": 800 * 1024 * 1024,
                "type": "audio",
            },
            "timeline": {
                "storage_key": "blobs/" + "1" * 64,
                "sha256": "1" * 64,
                "bytes": 1024,
                "type": "timeline_map",
            },
        },
    )
    packet = {"version": 1, "owner": "d" * 32, "command": request, "result": result}
    validator = Draft202012Validator(schemas()["agent.result.v1.schema.json"])
    assert validator.is_valid(packet), list(validator.iter_errors(packet))
    too_big = deepcopy(packet)
    too_big["result"]["outputs"]["timeline"]["bytes"] = 16 * 1024 * 1024 + 1
    assert not validator.is_valid(too_big)
    old = deepcopy(packet)
    old["command"]["agent"]["revision"] = "1"
    old["result"]["agent"]["revision"] = "1"
    old["command"]["options"] = {"vad_mode": "off"}
    del old["command"]["resource_budget"]
    assert not validator.is_valid(old)


def test_failed_long_sami_result_is_a_valid_failure_not_an_impossible_schema():
    request = {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": "generate_subtitle", "revision": "5"},
        "inputs": {
            "transcript": {
                "storage_key": "blobs/" + "c" * 64,
                "sha256": "c" * 64,
                "bytes": 100,
                "type": "transcript",
            }
        },
        "options": {"media_budget": ID, "format": "srt_smi"},
        "resource_budget": role_budget("generate_subtitle"),
    }
    result = {
        k: request[k]
        for k in ["protocol_version", "run_id", "attempt_id", "generation", "agent"]
    }
    result.update(
        request_sha256="e" * 64,
        status="failed",
        transport="s3_subprocess",
        outputs={},
        error={"code": "cpu_agent_failed", "retryable": False},
    )
    packet = {"version": 1, "owner": "d" * 32, "command": request, "result": result}
    validator = Draft202012Validator(schemas()["agent.result.v1.schema.json"])
    assert validator.is_valid(packet), list(validator.iter_errors(packet))


def test_runtime_cpu_wire_accepts_exact_v5_budget_and_still_rejects_tampering():
    import pytest
    from video_service.cpu_agents import digest
    from video_service.rabbitmq_transport import (
        InvalidMessage,
        validate_command,
        validate_result,
    )

    request = {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": "preprocess_audio", "revision": "5"},
        "inputs": {
            "audio": {
                "storage_key": "blobs/" + "c" * 64,
                "sha256": "c" * 64,
                "bytes": 800 * 1024 * 1024,
                "type": "audio",
            }
        },
        "options": {
            "media_budget": ID,
            "processing_profile": "regions_long_v5",
            "vad_mode": "off",
        },
        "resource_budget": role_budget("preprocess_audio"),
    }
    assert validate_command(request) == request
    result = {
        k: request[k]
        for k in ["protocol_version", "run_id", "attempt_id", "generation", "agent"]
    }
    result.update(
        request_sha256=digest(request),
        status="completed",
        transport="s3_subprocess",
        outputs={
            "audio": {
                "storage_key": "blobs/" + "f" * 64,
                "sha256": "f" * 64,
                "bytes": 800 * 1024 * 1024,
                "type": "audio",
            },
            "timeline": {
                "storage_key": "blobs/" + "1" * 64,
                "sha256": "1" * 64,
                "bytes": 1024,
                "type": "timeline_map",
            },
        },
    )
    assert validate_result(request, result) == result
    bad = deepcopy(request)
    bad["resource_budget"]["inputs"]["audio"] += 1
    with pytest.raises(InvalidMessage):
        validate_command(bad)
    bad_result = deepcopy(result)
    bad_result["outputs"]["timeline"]["bytes"] = 16 * 1024 * 1024 + 1
    with pytest.raises(InvalidMessage):
        validate_result(request, bad_result)
