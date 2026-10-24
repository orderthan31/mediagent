"""Versioned role budgets, not widened legacy defaults or storage permission."""

import importlib
import importlib.util

import pytest

budget = (
    importlib.import_module("video_service.long_audio_budget")
    if importlib.util.find_spec("video_service.long_audio_budget")
    else None
)


def test_explicit_role_budgets_separate_original_input_pcm_clock_and_outputs():
    assert callable(getattr(budget, "role_budget", None))
    extract = budget.role_budget("extract_audio")
    prepare = budget.role_budget("preprocess_audio")
    asr = budget.role_budget("transcribe")
    assert extract["inputs"]["video"] == 256 * 1024 * 1024
    assert extract["outputs"]["audio"] == 1024 * 1024 * 1024
    assert prepare["inputs"]["regions"] == 131072
    assert prepare["outputs"]["timeline"] == 16 * 1024 * 1024
    assert asr["outputs"]["trace"] == 16 * 1024 * 1024
    assert budget.policy()["original_storage_bytes"] == 4 * 1024 * 1024 * 1024
    assert budget.policy()["source_max_frames"] == 6 * 60 * 60 * 16000
    assert budget.policy()["packed_max_frames"] == 6 * 60 * 60 * 16000
    with pytest.raises(ValueError):
        budget.role_budget("faceswap")


def test_old_limits_remain_unchanged_and_new_budget_cannot_be_tampered():
    from video_service.cpu_input_policy import input_limit

    assert (
        input_limit({"id": "extract_audio", "revision": "1"}, "video", "video")
        == 256 * 1024 * 1024
    )
    assert (
        input_limit({"id": "preprocess_audio", "revision": "4"}, "audio", "audio")
        == 256 * 1024 * 1024
    )
    command = {
        "agent": {"id": "extract_audio", "revision": "5"},
        "options": {"media_budget": "audio_long_v5"},
        "resource_budget": budget.role_budget("extract_audio"),
    }
    budget.validate_command(command)
    command["resource_budget"]["outputs"]["audio"] += 1
    with pytest.raises(ValueError):
        budget.validate_command(command)


def test_long_clock_is_audio_and_frame_bound_while_old_reader_rejects_it():
    from video_service.audio_clock import registered_clock

    assert callable(getattr(budget, "make_clock", None))
    spans = [
        {"source_start": 0, "source_end": 601, "packed_start": 0, "packed_end": 601}
    ]
    clock = budget.make_clock(
        spans,
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        source_frames=601 * 16000,
        packed_frames=601 * 16000,
    )
    assert budget.read_clock(clock, audio_sha256="b" * 64) == spans
    with pytest.raises(ValueError):
        budget.read_clock(clock, audio_sha256="c" * 64)
    with pytest.raises(ValueError):
        registered_clock(clock, audio_sha256="b" * 64)
    clock["source_frames"] -= 1
    with pytest.raises(ValueError):
        budget.read_clock(clock, audio_sha256="b" * 64)


def test_default_process_output_ceiling_is_not_raised_for_legacy_callers(tmp_path):
    from video_service.cpu_agents import process_bounded

    with pytest.raises(ValueError, match="Invalid output budget"):
        process_bounded(
            [],
            output=tmp_path / "unused",
            cwd=tmp_path,
            timeout=1,
            max_bytes=1024 * 1024 * 1024,
        )


def test_partial_mixed_definition_and_oversized_frame_metadata_are_rejected():
    nodes = [
        {"type": "extract_audio", "options": {"media_budget": "audio_long_v5"}},
        {"type": "transcribe", "options": {}},
    ]
    with pytest.raises(ValueError, match="mixed"):
        budget.definition_policy({"nodes": nodes})
    with pytest.raises(ValueError):
        budget.make_clock(
            [{"source_start": 0, "source_end": 1, "packed_start": 0, "packed_end": 1}],
            source_sha256="a" * 64,
            audio_sha256="b" * 64,
            source_frames=budget.FRAMES + 1,
            packed_frames=16000,
        )


def test_model_command_budget_must_match_the_selected_call_deadline_not_a_role_ceiling():
    command = {
        "agent": {"id": "transcribe", "revision": "1"},
        "options": {"media_budget": "audio_long_v5", "max_model_calls": "8"},
        "resource_budget": budget.role_budget("transcribe"),
        "transcription": {"max_model_calls": 8, "max_runtime_seconds": 480},
    }
    with pytest.raises(ValueError):
        budget.validate_command(command)

    command["resource_budget"] = budget.command_budget("transcribe", command["options"])
    assert budget.validate_command(command)["lease_seconds"] == 480


def test_long_audio_does_not_remove_existing_bounded_encode_and_validation_steps():
    nodes = [
        {"type": "extract_audio", "options": {"media_budget": "audio_long_v5"}},
        {"type": "encode", "options": {}},
        {"type": "validate_video", "options": {}},
    ]
    selected = budget.definition_policy({"nodes": nodes})
    assert selected["legacy_roles"]["encode"]["input_bytes"] == 256 * 1024 * 1024
    assert selected["legacy_roles"]["encode"]["command_seconds"] == 90


def test_unrelated_gpu_engine_revision_does_not_mean_cpu_audio_v5():
    assert (
        budget.validate_command(
            {
                "protocol_version": 2,
                "agent": {"id": "preprocess_audio", "revision": "5", "family": "gpu"},
                "options": {},
            }
        )
        is None
    )


def test_human_wait_is_not_falsely_reported_as_a_worker_lease():
    assert "lease_seconds" not in budget.role_budget("review")


def test_malformed_cpu_agent_remains_a_clean_value_error(tmp_path):
    from video_service.cpu_agents import run

    command = {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": None,
        "inputs": {},
        "options": {},
    }
    with pytest.raises(ValueError):
        run(command, tmp_path, tmp_path)


def test_long_profile_preserves_srt_only_and_legacy_analysis_choice():
    selected = budget.definition_policy(
        {
            "nodes": [
                {"type": "analyze", "options": {}},
                {
                    "type": "generate_subtitle",
                    "options": {"media_budget": "audio_long_v5", "format": "srt"},
                },
            ]
        }
    )
    assert selected["legacy_roles"]["analyze"]["input_bytes"] == 256 * 1024 * 1024


def test_cpu_long_budget_cannot_be_used_as_a_gpu_engine_contract():
    command = {
        "protocol_version": 2,
        "agent": {"id": "preprocess_audio", "revision": "5", "family": "gpu"},
        "options": {"media_budget": "audio_long_v5"},
        "resource_budget": budget.role_budget("preprocess_audio"),
    }
    with pytest.raises(ValueError):
        budget.validate_command(command)


def test_serialized_sami_over_budget_is_rejected_before_the_output_file_is_written(
    tmp_path,
):
    from video_service.content_store import ContentStore
    from video_service.cpu_agents import canonical, run

    root = tmp_path / "store"
    root.mkdir()
    store = ContentStore(root)
    owner = "a" * 32
    rows = [{"start": i, "end": i + 0.5, "text": "&" * 16000} for i in range(220)]
    ref = store.put(owner, [canonical(rows)], "transcript")
    output = tmp_path / "output"
    output.mkdir()
    command = {
        "protocol_version": 1,
        "run_id": "b" * 32,
        "attempt_id": "c" * 32,
        "generation": 1,
        "agent": {"id": "generate_subtitle", "revision": "5"},
        "inputs": {"transcript": ref},
        "options": {
            "media_budget": "audio_long_v5",
            "format": "srt_smi",
            "language": "en",
        },
        "resource_budget": budget.role_budget("generate_subtitle"),
    }
    result = run(command, store.owner_root(owner), output)
    assert result["status"] == "failed"
    assert not (output / ("b" * 32 + "-" + "c" * 32) / "subtitles.smi").exists()
