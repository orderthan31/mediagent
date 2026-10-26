from uuid import uuid4

import pytest
from video_service.original_video_budget import ID, role_budget
from video_service.rabbitmq_transport import validate_command


@pytest.mark.parametrize(
    "role", ["analyze", "extract_audio", "encode", "validate_video"]
)
def test_original_video_role_wire_is_explicit_and_finite(role):
    command = {
        "protocol_version": 1,
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "generation": 1,
        "agent": {"id": role, "revision": "6"},
        "inputs": {
            "video": {
                "type": "video",
                "storage_key": "blobs/" + "a" * 64,
                "sha256": "a" * 64,
                "bytes": 674707577,
            }
        },
        "options": {"media_budget": ID},
        "resource_budget": role_budget(role),
    }
    if role == "encode":
        command["options"]["subtitle_mode"] = "none"
    validate_command(command)
    from jsonschema import Draft202012Validator
    from video_service.agent_protocol import schemas

    schema = schemas()["agent.command.v1.schema.json"]
    Draft202012Validator(schema).validate(
        {"version": 1, "owner": uuid4().hex, "command": command}
    )
    command["resource_budget"]["inputs"]["video"] += 1
    with pytest.raises(ValueError):
        validate_command(command)
