"""Actual BOLT02 metadata must use independent full-role admission, never an encode-only loophole."""

import json
from pathlib import Path

import pytest
from video_service.cpu_input_policy import input_limit, source_policy


def materials():
    root = Path(__file__).parent
    return json.loads((root / "bolt02-source-metadata.json").read_text()), json.loads(
        (root / "bolt02-definition-r3.json").read_text()
    )


def test_real_bolt02_full_workflow_source_admission_has_per_role_budgets():
    asset, definition = materials()
    policy = source_policy(asset, definition)
    assert policy["id"] == "original_video_v6"
    assert policy["roles"]["extract_audio"]["inputs"]["video"] == 4294967296
    assert policy["roles"]["extract_audio"]["outputs"]["audio"] == 1073741824
    assert policy["roles"]["encode"]["outputs"]["video"] == 4294967296
    assert policy["roles"]["validate_video"]["inputs"]["video"] == 4294967296


def test_original_video_budget_does_not_change_legacy_or_v5_limits():
    assert (
        input_limit({"id": "extract_audio", "revision": "1"}, "video", "video")
        == 268435456
    )
    assert (
        input_limit({"id": "extract_audio", "revision": "5"}, "video", "video")
        == 268435456
    )
    assert (
        input_limit({"id": "extract_audio", "revision": "6"}, "video", "video")
        == 4294967296
    )


def test_unverified_or_over_budget_originals_still_rejected():
    asset, definition = materials()
    asset["metadata"]["registration_state"] = "unverified"
    with pytest.raises(ValueError):
        source_policy(asset, definition)
    asset, definition = materials()
    asset["bytes"] = 4294967297
    with pytest.raises(ValueError):
        source_policy(asset, definition)
