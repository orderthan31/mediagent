"""Versioned wire contract constants and machine-readable CPU request/response schemas.

Schemas describe transport shapes. Runtime validators additionally fence owner,
request digest, exact role/port types and object key/hash equality.
"""

from copy import deepcopy

CPU_AGENTS = frozenset(
    {
        "analyze",
        "extract_audio",
        "preprocess_audio",
        "generate_subtitle",
        "encode",
        "validate_video",
    }
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
        "properties": {
            "id": {"enum": sorted(CPU_AGENTS)},
            "revision": {"enum": ["1", "3", "4", "5"]},
        },
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
            "resource_budget": {"type": "object"},
        },
        "oneOf": [],
    }
    for role in sorted(CPU_AGENTS):
        spec = node_spec(role)
        assert spec is not None
        ports = {
            port: {
                "allOf": [
                    {"$ref": "#/$defs/input_artifact"},
                    {"properties": {"type": {"const": kind}}},
                ]
            }
            for port, kind in spec["inputs"].items()
        }
        branch = {
            "properties": {
                "agent": {
                    "properties": {"id": {"const": role}, "revision": {"const": "1"}}
                },
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
        if role == "preprocess_audio":
            branch["properties"]["agent"]["properties"]["revision"] = {
                "enum": ["1", "3", "4"]
            }
            branch["properties"]["options"]["properties"]["processing_profile"] = {
                "enum": ["legacy_v1", "silence_pack_v3", "regions_pack_v4"]
            }
            branch["allOf"] = []
            for revision, profile in [
                ("1", "legacy_v1"),
                ("3", "silence_pack_v3"),
                ("4", "regions_pack_v4"),
            ]:
                opts = {"properties": {"processing_profile": {"const": profile}}}
                if revision != "1":
                    opts["required"] = ["processing_profile"]
                    opts["properties"]["vad_mode"] = {"enum": ["off"]}
                inputs_rule = (
                    {"required": ["regions"]}
                    if revision == "4"
                    else {"not": {"required": ["regions"]}}
                )
                branch["allOf"].append(
                    {
                        "if": {
                            "properties": {
                                "agent": {
                                    "properties": {"revision": {"const": revision}}
                                }
                            }
                        },
                        "then": {
                            "properties": {"options": opts, "inputs": inputs_rule}
                        },
                    }
                )
        if role == "generate_subtitle":
            branch["properties"]["agent"]["properties"]["revision"] = {
                "enum": ["1", "3"]
            }
            branch["properties"]["options"]["properties"]["language"] = {
                "type": "string",
                "pattern": "^[a-z]{2,3}$",
            }
            branch["allOf"] = [
                {
                    "if": {
                        "properties": {
                            "agent": {"properties": {"revision": {"const": "3"}}}
                        }
                    },
                    "then": {
                        "properties": {
                            "options": {
                                "required": ["format"],
                                "properties": {"format": {"const": "srt_smi"}},
                            }
                        }
                    },
                    "else": {
                        "properties": {
                            "options": {"properties": {"format": {"enum": ["srt"]}}}
                        }
                    },
                }
            ]
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
        from .long_audio_budget import CPU_ROLES, ID, role_budget

        if role in CPU_ROLES:
            budget = role_budget(role)
            long_branch = deepcopy(branch)
            long_branch.pop("allOf", None)
            long_branch["required"] = ["resource_budget"]
            long_branch["properties"]["resource_budget"] = {"const": budget}
            long_branch["properties"]["agent"]["properties"]["revision"] = {
                "const": "5"
            }
            long_branch["properties"]["options"]["required"] = ["media_budget"]
            long_branch["properties"]["options"]["properties"]["media_budget"] = {
                "const": ID
            }
            if role == "preprocess_audio":
                long_branch["properties"]["options"]["required"].append(
                    "processing_profile"
                )
                long_branch["properties"]["options"]["properties"].update(
                    processing_profile={"const": "regions_long_v5"},
                    vad_mode={"const": "off"},
                )
            if role == "generate_subtitle":
                long_branch["properties"]["options"]["required"].append("format")
                long_branch["properties"]["options"]["properties"]["format"] = {
                    "enum": ["srt", "srt_smi"]
                }
            long_ports = {}
            for port, kind in spec["inputs"].items():
                ref = deepcopy(artifact)
                ref["properties"]["source_owner_id"] = identity
                ref["properties"]["bytes"]["maximum"] = budget["inputs"][port]
                ref["properties"]["type"] = {"const": kind}
                long_ports[port] = ref
            long_branch["properties"]["inputs"]["properties"] = long_ports
            command["oneOf"].append(long_branch)
            branch["properties"]["options"]["properties"]["media_budget"] = {
                "enum": ["legacy"]
            }
        branch["properties"]["resource_budget"] = False
        command["oneOf"].append(branch)
    base = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "owner", "command"],
        "$defs": {
            "artifact": artifact,
            "input_artifact": {
                **deepcopy(artifact),
                "properties": {
                    **deepcopy(artifact["properties"]),
                    "source_owner_id": identity,
                },
            },
        },
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
    result_fields.pop("resource_budget")
    result_fields.update(
        {
            "request_sha256": sha,
            "status": {"enum": ["completed", "failed"]},
            "transport": {"const": "s3_subprocess"},
            "outputs": {
                "type": "object",
                "additionalProperties": True,
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
    long_results = []
    from .long_audio_budget import CPU_ROLES, role_budget

    for role in sorted(CPU_ROLES):
        budget = role_budget(role)
        outputs = {}
        for port, maximum in budget["outputs"].items():
            ref = deepcopy(artifact)
            ref["properties"]["bytes"]["maximum"] = maximum
            ref["properties"]["type"] = {
                "const": node_spec(role, {"format": "srt_smi"})["outputs"][port]
            }
            outputs[port] = ref
        long_results.append(
            {
                "properties": {
                    "agent": {"properties": {"id": {"const": role}}},
                    "outputs": {
                        "type": "object",
                        "properties": outputs,
                        "additionalProperties": False,
                    },
                },
                "if": {"properties": {"status": {"const": "completed"}}},
                "then": {
                    "properties": {
                        "outputs": {
                            "required": ["subtitles"]
                            if role == "generate_subtitle"
                            else list(outputs)
                        }
                    }
                },
            }
        )
    result["allOf"] = [
        {
            "if": {
                "properties": {"agent": {"properties": {"revision": {"const": "5"}}}}
            },
            "then": {"oneOf": long_results},
            "else": {
                "properties": {
                    "outputs": {"additionalProperties": {"$ref": "#/$defs/artifact"}}
                }
            },
        }
    ]
    response["required"].append("result")
    response["properties"]["result"] = result
    response["allOf"] = [
        {
            "if": {
                "properties": {
                    "result": {"properties": {"status": {"const": "completed"}}},
                    "command": {
                        "properties": {
                            "agent": {
                                "properties": {
                                    "id": {"const": "generate_subtitle"},
                                    "revision": {"const": "5"},
                                }
                            }
                        }
                    },
                }
            },
            "then": {
                "if": {
                    "properties": {
                        "command": {
                            "properties": {
                                "options": {
                                    "properties": {"format": {"const": "srt_smi"}}
                                }
                            }
                        }
                    }
                },
                "then": {
                    "properties": {
                        "result": {"properties": {"outputs": {"required": ["sami"]}}}
                    }
                },
                "else": {
                    "properties": {
                        "result": {
                            "properties": {"outputs": {"not": {"required": ["sami"]}}}
                        }
                    }
                },
            },
        }
    ]
    return {
        "agent.command.v1.schema.json": request,
        "agent.result.v1.schema.json": response,
    }
