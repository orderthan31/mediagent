"""Machine-readable contract matches opt-in subtitle v3, without widening v1."""

from copy import deepcopy

from jsonschema import Draft202012Validator
from video_service.agent_protocol import schemas


def test_subtitle_v3_is_explicit_in_wire_schema_and_cannot_be_used_by_other_roles():
    validator = Draft202012Validator(schemas()["agent.command.v1.schema.json"])
    command = {
        "version": 1,
        "owner": "a" * 32,
        "command": {
            "protocol_version": 1,
            "run_id": "b" * 32,
            "attempt_id": "c" * 32,
            "generation": 1,
            "agent": {"id": "generate_subtitle", "revision": "3"},
            "inputs": {
                "transcript": {
                    "storage_key": "blobs/" + "d" * 64,
                    "sha256": "d" * 64,
                    "bytes": 100,
                    "type": "transcript",
                }
            },
            "options": {"format": "srt_smi", "language": "uk"},
        },
    }
    assert validator.is_valid(command), list(validator.iter_errors(command))
    old = deepcopy(command)
    old["command"]["agent"]["revision"] = "1"
    old["command"]["options"] = {}
    assert validator.is_valid(old)
    mixed = deepcopy(command)
    mixed["command"]["agent"]["revision"] = "1"
    assert not validator.is_valid(mixed), (
        "SAMI export may not masquerade as old subtitle revision 1"
    )
    bad = deepcopy(command)
    bad["command"]["agent"]["id"] = "encode"
    assert not validator.is_valid(bad)
