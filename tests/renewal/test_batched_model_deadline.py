"""New batched node lease is frozen/bounded, never a global timeout increase."""

import pytest
from video_service.cpu_input_policy import lease_seconds


def test_batched_model_node_uses_its_explicit_frozen_deadline_not_legacy_120_seconds():
    old = {"agent": {"id": "transcribe", "revision": "1"}}
    assert lease_seconds(old) == 120
    command = {
        **old,
        "transcription": {
            "batch_policy": "bounded_60s_v1",
            "max_model_calls": 128,
            "max_runtime_seconds": 5880,
        },
    }
    assert lease_seconds(command) == 5880
    invalid = {
        **command,
        "transcription": {**command["transcription"], "max_runtime_seconds": 999999},
    }
    with pytest.raises(ValueError):
        lease_seconds(invalid)
    assert lease_seconds({"agent": {"id": "encode", "revision": "1"}}) == 120
