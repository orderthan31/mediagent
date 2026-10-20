"""Pinned offline model/GPU wire, deliberately separate from CPU-v1 queues."""

import json
import re
from .cpu_agents import canonical, digest
from .node_contracts import node_spec, validate_node
from .rabbitmq_transport import Delivery, InvalidMessage, MAX_MESSAGE

COMMAND = "agent.engine.command.v2"
RESULT = "agent.engine.result.v2"
ENGINE_ROLES = frozenset({"transcribe", "translate", "preprocess_audio", "faceswap"})
ENGINES = {
    "transcribe": "whisper-tiny-en",
    "translate": "opus-en-de-int8",
    "preprocess_audio": "nvidia-marblenet",
    "faceswap": "facefusion-3.9.0",
}
ID = re.compile(r"[a-f0-9]{32}")
SHA = re.compile(r"[a-f0-9]{64}")


def validate_runtime(value):
    if not isinstance(value, dict) or set(value) != {
        "role",
        "family",
        "engine",
        "model_sha256",
        "source_language",
        "target_language",
    }:
        raise ValueError("invalid_engine_descriptor")
    role = value["role"]
    family = "model" if role in {"transcribe", "translate"} else "gpu"
    if (
        role not in ENGINE_ROLES
        or value["family"] != family
        or value["engine"] != ENGINES[role]
        or not isinstance(value["model_sha256"], str)
        or not SHA.fullmatch(value["model_sha256"])
    ):
        raise ValueError("invalid_engine_descriptor")
    pair = (
        ("en", "de")
        if role == "translate"
        else ("en", None)
        if role == "transcribe"
        else (None, None)
    )
    if (value["source_language"], value["target_language"]) != pair:
        raise ValueError("unsupported_installed_engine_language")
    return value


def reference(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"storage_key", "sha256", "bytes", "type"}
        or not isinstance(value["sha256"], str)
        or not SHA.fullmatch(value["sha256"])
        or value["storage_key"] != "blobs/" + value["sha256"]
        or type(value["bytes"]) is not int
        or not 0 < value["bytes"] <= 268435456
    ):
        raise ValueError("invalid_engine_artifact")


def validate_command(command):
    if not isinstance(command, dict) or set(command) != {
        "protocol_version",
        "run_id",
        "attempt_id",
        "generation",
        "agent",
        "inputs",
        "options",
        "runtime",
    }:
        raise ValueError("invalid_engine_command")
    if (
        type(command["protocol_version"]) is not int
        or command["protocol_version"] != 2
        or type(command["generation"]) is not int
        or command["generation"] < 1
    ):
        raise ValueError("invalid_engine_version_generation")
    if any(
        not isinstance(command[k], str) or not ID.fullmatch(command[k])
        for k in ["run_id", "attempt_id"]
    ):
        raise ValueError("invalid_engine_identity")
    runtime = validate_runtime(command["runtime"])
    role = runtime["role"]
    if command["agent"] != {
        "id": role,
        "family": runtime["family"],
        "revision": digest(runtime),
    }:
        raise ValueError("engine_revision_mismatch")
    if not isinstance(command["inputs"], dict):
        raise ValueError("invalid_engine_inputs")
    for ref in command["inputs"].values():
        reference(ref)
    validate_node(
        {
            "node": role,
            "inputs": {k: v["type"] for k, v in command["inputs"].items()},
            "options": command["options"],
        }
    )
    if role == "preprocess_audio" and command["options"].get("vad_mode") != "nvidia":
        raise ValueError("gpu_preprocess_requires_explicit_nvidia")
    return command


def make_command(role, *, run_id, attempt_id, generation, inputs, options, runtime):
    command = {
        "protocol_version": 2,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "generation": generation,
        "agent": {"id": role, "family": runtime["family"], "revision": digest(runtime)},
        "inputs": inputs,
        "options": options,
        "runtime": runtime,
    }
    validate_command(command)
    return command


def envelope(owner, command, result=None):
    try:
        if not isinstance(owner, str) or not ID.fullmatch(owner):
            raise ValueError
        validate_command(command)
        value = {"version": 1, "owner": owner, "command": command}
        if result is not None:
            required = {
                "protocol_version",
                "run_id",
                "attempt_id",
                "generation",
                "agent",
                "request_sha256",
                "status",
                "transport",
                "outputs",
            }
            if (
                not isinstance(result, dict)
                or set(result) - required - {"error"}
                or not required <= set(result)
            ):
                raise ValueError
            if (
                type(result["protocol_version"]) is not int
                or type(result["generation"]) is not int
                or not isinstance(result["outputs"], dict)
            ):
                raise ValueError
            if (
                any(
                    result[k] != command[k]
                    for k in [
                        "protocol_version",
                        "run_id",
                        "attempt_id",
                        "generation",
                        "agent",
                    ]
                )
                or result["request_sha256"] != digest(command)
                or result["transport"] != "s3_engine"
            ):
                raise ValueError
            if result["status"] == "completed":
                expected = node_spec(command["agent"]["id"], command["options"])[
                    "outputs"
                ]
                if "error" in result or set(result["outputs"]) != set(expected):
                    raise ValueError
                for port, ref in result["outputs"].items():
                    reference(ref)
                    if ref["type"] != expected[port]:
                        raise ValueError
            elif result["status"] == "failed":
                error = result.get("error")
                if (
                    result["outputs"] != {}
                    or not isinstance(error, dict)
                    or set(error) != {"code", "retryable"}
                    or not isinstance(error["code"], str)
                    or not re.fullmatch("[a-z][a-z0-9_]{0,63}", error["code"])
                    or type(error["retryable"]) is not bool
                ):
                    raise ValueError
            else:
                raise ValueError
            value["result"] = result
        body = canonical(value)
        if len(body) > MAX_MESSAGE:
            raise ValueError
        return Delivery(
            body,
            RESULT if result is not None else COMMAND,
            command["attempt_id"],
            command["run_id"],
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise InvalidMessage("invalid_engine_message") from None


def decode(delivery, *, result=False, role=None):
    try:
        if (
            len(delivery.body) > MAX_MESSAGE
            or delivery.message_type != (RESULT if result else COMMAND)
            or delivery.content_type != "application/json"
            or delivery.content_encoding != "utf-8"
        ):
            raise ValueError
        value = json.loads(delivery.body)
        if (
            set(value)
            != {"version", "owner", "command", *(["result"] if result else [])}
            or type(value["version"]) is not int
            or value["version"] != 1
        ):
            raise ValueError
        expected = envelope(value["owner"], value["command"], value.get("result"))
        if (
            expected.message_id != delivery.message_id
            or expected.correlation_id != delivery.correlation_id
            or role is not None
            and value["command"]["agent"]["id"] != role
        ):
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise InvalidMessage("invalid_engine_delivery") from None
