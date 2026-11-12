"""Selected overlapping cues through real source handlers and SRT serialization.

Existing memory/CAS fixtures only: no DB, services, provider or product assets.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from test_normal_inputs import (
    ROOT, ROWS, SRT, accepted_inputs, connect_accepted_runtime, inline_runtime,
    input_graph, mount_actual_input_handlers, recovery_runtime, source_execution,
)

sys.path.insert(0, str(ROOT / "tools/media"))

OVERLAP = [
    {"id": "007", "start": 10, "end": 11, "text": " A \nsecond line", "speaker": "one"},
    {"id": 2, "start": 10.5, "end": 11.5, "text": "B", "speaker": "two"},
]
OVERLAP_SRT = (
    "007\n00:00:10,000 --> 00:00:11,000\n A \nsecond line\n\n"
    "2\n00:00:10,500 --> 00:00:11,500\nB\n"
)


@pytest.fixture
def tmp_path(monkeypatch):
    root = (
        Path("C:/Users/skygg/AppData/Local/hermes/cache/scratch/mediagent-5178-parity/selected-srt-overlap")
        if os.name == "nt" else Path("/tmp/selected-srt-overlap")
    )
    folder = root / uuid4().hex
    folder.mkdir(parents=True)
    if os.name == "nt":
        # Python 3.14's mode=0700 removes the managed runner's inherited ACL.
        # Only our private unit tree uses inherited ACLs; storage validation and
        # real source/custodian path handling remain unchanged.
        mkdir = Path.mkdir

        def unit_mkdir(path, mode=0o777, parents=False, exist_ok=False):
            if path.is_relative_to(folder) and mode == 0o700:
                mode = 0o777
            return mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", unit_mkdir)
    return folder


def test_accepted_overlapping_speakers_preview_create_and_real_srt_keep_cues(
    accepted_inputs, inline_runtime, tmp_path,
):
    from mideagent_media_tools.operations import run
    from video_service.audio_contract import timed_segments as accepted_speech
    from video_service.canonical import canonical

    state = accepted_inputs
    runtime, parent, graph, writes = inline_runtime
    # Same overlapping-speaker intervals accepted by the actual ASR contract.
    assert [r["speaker"] for r in accepted_speech(OVERLAP, 12)] == ["one", "two"]
    original = canonical(OVERLAP)
    reference = state.runtime.store.put(state.job["owner_id"], [original], "transcript")
    state.runs[1]["result"]["outputs"]["transcript"] = reference
    connect_accepted_runtime(runtime, parent, graph, state)
    before = deepcopy((state.job, state.runs))
    handlers = mount_actual_input_handlers(runtime)
    selector = {"job_id": state.job["id"], "run_id": state.runs[1]["id"], "port": "transcript"}
    selection = handlers["Selection"](
        asset_id=state.asset["asset_id"], definition_id=parent["workflow_id"],
        definition_revision=1, options={"accepted_inputs": {"transcript": selector}},
    )
    preview = handlers["preview"](selection, state.actor)
    assert preview["paid_roles"] == [] and not writes
    assert preview["selected_inputs"][0]["language"] == "ja"
    assert preview["selected_inputs"][0]["segments"] == 2
    child = handlers["create"](
        handlers["Create"](**selection.model_dump(), token=preview["token"], request_id="unit-overlap-accepted"),
        state.actor,
    )
    snapshot = child["snapshot"]
    bound = snapshot["inputs"]["transcript"]
    assert bound == {**reference, "source_owner_id": state.job["owner_id"]}
    pin = snapshot["normal_input_bindings"]["transcript"]
    assert pin["custodian_id"] == state.job["owner_id"] and pin["language"] == "ja"
    assert {key: pin[key] for key in selector} == selector
    assert snapshot["model_bindings"] == {} and not writes and not runtime.database.outbox
    assert state.runtime.store.read(state.actor, bound) == original

    node = snapshot["definition"]["nodes"][0]
    assert node["type"] == "generate_subtitle"
    assert node["options"]["format"] == "srt" and node["options"]["cue_policy"] == "preserve_v1"
    assert node["options"]["language"] == "ja"
    _, command = runtime._insert_run(runtime.database, child, node, {"transcript": bound}, "running")
    assert command["inputs"]["transcript"] == bound
    output = tmp_path / "overlap-output"
    output.mkdir()
    result = run(command, state.runtime.store.owner_root(state.actor), output)
    assert result["status"] == "completed", result
    serialized = (output / result["outputs"]["subtitles"]["storage_key"]).read_bytes()
    assert serialized == OVERLAP_SRT.encode("utf-8")
    assert state.runtime.store.read(state.actor, bound) == original
    assert (state.job, state.runs) == before


def test_overlapping_srt_file_uses_actual_preview_create_without_retiming(inline_runtime):
    from video_service.timed_subtitles import preserved_files

    runtime, parent, graph, writes = inline_runtime
    handlers = mount_actual_input_handlers(runtime)
    selection = handlers["Selection"](
        asset_id=parent["asset_id"], definition_id=parent["workflow_id"], definition_revision=1,
        options={"subtitle_srt": OVERLAP_SRT, "input_language": "ja"},
    )
    preview = handlers["preview"](selection, parent["owner_id"])
    assert not writes and preview["selected_inputs"][0]["segments"] == 2
    child = handlers["create"](
        handlers["Create"](**selection.model_dump(), token=preview["token"], request_id="unit-overlap-srt"),
        parent["owner_id"],
    )
    expected = [{**row, "id": str(row["id"])} for row in OVERLAP]
    expected = [{key: value for key, value in row.items() if key != "speaker"} for row in expected]
    assert len(writes) == 1 and json.loads(writes[0]) == expected
    options = child["snapshot"]["definition"]["nodes"][0]["options"]
    assert preserved_files(json.loads(writes[0]), options)["subtitles"] == OVERLAP_SRT.encode("utf-8")
    assert not runtime.database.outbox


@pytest.mark.parametrize("consumer,reason", [("translation", "순서/시각"), ("sami", "Overlapping")])
def test_overlapping_cues_still_fail_at_the_unsupported_consumer_before_create(
    inline_runtime, consumer, reason,
):
    runtime, parent, graph, writes = inline_runtime
    graph.clear()
    graph.update(input_graph(translated=consumer == "translation"))
    if consumer == "sami":
        graph["nodes"][0]["options"]["format"] = "srt_smi"
    handlers = mount_actual_input_handlers(runtime)
    selection = handlers["Selection"](
        asset_id=parent["asset_id"], definition_id=parent["workflow_id"], definition_revision=1,
        options={"transcript": deepcopy(OVERLAP), "input_language": "ja"},
    )
    with pytest.raises(ValueError, match=reason):
        handlers["preview"](selection, parent["owner_id"])
    assert not writes and not runtime.database.children and not runtime.database.outbox


def test_nonoverlapping_preserve_stays_literal_and_duplicate_ids_stay_invalid():
    from video_service.canonical import canonical
    from video_service.timed_subtitles import preserved_files, timed_segments

    before = deepcopy(ROWS)
    assert preserved_files(ROWS, {"format": "srt", "cue_policy": "preserve_v1"}) == {"subtitles": SRT.encode("utf-8")}
    assert ROWS == before
    duplicate = deepcopy(OVERLAP)
    duplicate[1]["id"] = duplicate[0]["id"]
    with pytest.raises(ValueError, match="ID 중복"):
        timed_segments(duplicate)
    with pytest.raises(ValueError, match="이내"):
        timed_segments(OVERLAP, maximum=len(canonical(OVERLAP)) - 1)


@pytest.mark.parametrize("policy", [None, "reflow_v1"])
def test_absent_and_explicit_legacy_reflow_keep_exact_old_output(tmp_path, policy):
    from mideagent_media_tools.operations import run
    from video_service.canonical import canonical, digest

    rows = [{"id": "007", "start": 0, "end": 10, "text": "a" * 100}]
    raw, sha = canonical(rows), digest(rows)
    inputs = tmp_path / "legacy-input"
    (inputs / "blobs").mkdir(parents=True)
    (inputs / "blobs" / sha).write_bytes(raw)
    output = tmp_path / "legacy-output"
    output.mkdir()
    options = {"format": "srt"}
    if policy is not None:
        options["cue_policy"] = policy
    command = {
        "protocol_version": 1, "run_id": "b" * 32, "attempt_id": "c" * 32, "generation": 1,
        "agent": {"id": "generate_subtitle", "revision": "1"},
        "inputs": {"transcript": {"storage_key": "blobs/" + sha, "sha256": sha, "bytes": len(raw), "type": "transcript"}},
        "options": options,
    }
    result = run(command, inputs, output)
    assert result["status"] == "completed", result
    expected = (
        f"1\n00:00:00,000 --> 00:00:08,400\n{'a' * 42}\n{'a' * 42}\n\n"
        f"2\n00:00:08,400 --> 00:00:10,000\n{'a' * 16}\n"
    )
    assert (output / result["outputs"]["subtitles"]["storage_key"]).read_text(encoding="utf-8") == expected
    assert (inputs / "blobs" / sha).read_bytes() == raw
