"""Versioned wire contract constants and machine-readable CPU request/response schemas.

Schemas describe transport shapes. Runtime validators additionally fence owner,
request digest, exact role/port types and object key/hash equality.
"""

from copy import deepcopy

CPU_AGENTS = frozenset(
    {"analyze", "extract_audio", "generate_subtitle", "encode", "validate_video"}
)
PROTOCOL_VERSION = 1
COMMAND = "agent.command.v1"
RESULT = "agent.result.v1"
MAX_MESSAGE = 131072


def schemas():
    from .node_contracts import node_spec

    identity = {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    sha = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    artifact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["storage_key", "sha256", "bytes", "type"],
        "properties": {
            "storage_key": {"type": "string", "pattern": "^blobs/[a-f0-9]{64}$"},
            "sha256": sha,
            "bytes": {"type": "integer", "minimum": 1, "maximum": 268435456},
            "type": {"type": "string"},
        },
    }
    agent = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "revision"],
        "properties": {"id": {"enum": sorted(CPU_AGENTS)}, "revision": {"const": "1"}},
    }
    command = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "protocol_version",
            "run_id",
            "attempt_id",
            "generation",
            "agent",
            "inputs",
            "options",
        ],
        "properties": {
            "protocol_version": {"const": 1, "type": "integer"},
            "run_id": identity,
            "attempt_id": identity,
            "generation": {"type": "integer", "minimum": 1},
            "agent": agent,
            "inputs": {"type": "object"},
            "options": {"type": "object"},
        },
        "oneOf": [],
    }
    for role in sorted(CPU_AGENTS):
        spec = node_spec(role)
        assert spec is not None
        ports = {
            port: {
                "allOf": [
                    {"$ref": "#/$defs/artifact"},
                    {"properties": {"type": {"const": kind}}},
                ]
            }
            for port, kind in spec["inputs"].items()
        }
        branch = {
            "properties": {
                "agent": {"properties": {"id": {"const": role}}},
                "inputs": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": ports,
                    "required": sorted(set(ports) - set(spec["optional_inputs"])),
                },
                "options": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        key: {"enum": values} for key, values in spec["options"].items()
                    },
                },
            }
        }
        if role == "encode":
            branch["if"] = {
                "properties": {
                    "options": {
                        "required": ["subtitle_mode"],
                        "properties": {"subtitle_mode": {"const": "none"}},
                    }
                }
            }
            branch["then"] = {
                "properties": {"inputs": {"not": {"required": ["subtitles"]}}}
            }
            branch["else"] = {"properties": {"inputs": {"required": ["subtitles"]}}}
        command["oneOf"].append(branch)
    base = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "owner", "command"],
        "$defs": {"artifact": artifact},
        "properties": {
            "version": {"const": 1, "type": "integer"},
            "owner": identity,
            "command": command,
        },
    }
    request = {"$id": "urn:mideagent:agent.command.v1", **deepcopy(base)}
    response = {"$id": "urn:mideagent:agent.result.v1", **deepcopy(base)}
    result_fields = deepcopy(command["properties"])
    result_fields.pop("inputs")
    result_fields.pop("options")
    result_fields.update(
        {
            "request_sha256": sha,
            "status": {"enum": ["completed", "failed"]},
            "transport": {"const": "s3_subprocess"},
            "outputs": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/artifact"},
            },
            "error": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "retryable"],
                "properties": {
                    "code": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
                    "retryable": {"type": "boolean"},
                },
            },
        }
    )
    result = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(set(result_fields) - {"error"}),
        "properties": result_fields,
        "if": {"properties": {"status": {"const": "failed"}}},
        "then": {
            "required": ["error"],
            "properties": {"outputs": {"maxProperties": 0}},
        },
        "else": {
            "not": {"required": ["error"]},
            "properties": {"outputs": {"minProperties": 1}},
        },
    }
    response["required"].append("result")
    response["properties"]["result"] = result
    return {
        "agent.command.v1.schema.json": request,
        "agent.result.v1.schema.json": response,
    }
