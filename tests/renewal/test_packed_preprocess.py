"""Changed-boundary real PCM packing tests; no model, DB or network calls."""

import hashlib
import io
import json
import math
import struct
import wave
from uuid import uuid4

from video_service.audio_clock import restore_clock
from video_service.cpu_agents import run


def pcm_fixture(root, *, silence_seconds=6):
    (root / "blobs").mkdir()
    (root / "outputs").mkdir()
    tone = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
        for i in range(16000)
    )
    pcm = tone + bytes(silence_seconds * 32000) + tone
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    raw = buffer.getvalue()
    sha = hashlib.sha256(raw).hexdigest()
    (root / "blobs" / sha).write_bytes(raw)
    return pcm, {
        "protocol_version": 1,
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "generation": 1,
        "agent": {"id": "preprocess_audio", "revision": "3"},
        "inputs": {
            "audio": {
                "storage_key": "blobs/" + sha,
                "sha256": sha,
                "bytes": len(raw),
                "type": "audio",
            }
        },
        "options": {
            "processing_profile": "silence_pack_v3",
            "audio_filter": "strong",
            "vad_mode": "off",
        },
    }


def test_selected_strong_filter_packs_exact_pcm_and_restores_source_clock(tmp_path):
    original, command = pcm_fixture(tmp_path)
    result = run(command, tmp_path, tmp_path / "outputs", agent="preprocess_audio")
    assert result["status"] == "completed", result
    refs = result["outputs"]
    mapping = json.loads(
        (tmp_path / "outputs" / refs["timeline"]["storage_key"]).read_bytes()
    )
    assert len(mapping) == 2
    with wave.open(
        str(tmp_path / "outputs" / refs["audio"]["storage_key"]), "rb"
    ) as audio:
        packed = audio.readframes(audio.getnframes())
        assert 2.39 < audio.getnframes() / 16000 < 2.41
    expected = b"".join(
        original[
            round(s["source_start"] * 16000) * 2 : round(s["source_end"] * 16000) * 2
        ]
        for s in mapping
    )
    assert packed == expected
    boundary = mapping[0]["packed_end"]
    segments = [
        {
            "id": "cue-1",
            "start": boundary,
            "end": boundary + 0.1,
            "text": "timing fixture",
            "speaker": "A",
        }
    ]
    restored = restore_clock(segments, mapping)
    assert restored[0]["start"] == mapping[1]["source_start"]
    assert restored[0]["id"] == "cue-1" and restored[0]["speaker"] == "A"
    for ref in refs.values():
        assert (
            hashlib.sha256(
                (tmp_path / "outputs" / ref["storage_key"]).read_bytes()
            ).hexdigest()
            == ref["sha256"]
        )


def test_new_preprocess_wire_is_explicit_and_old_revision_cannot_claim_it(tmp_path):
    from copy import deepcopy

    from jsonschema import Draft202012Validator
    from video_service.agent_protocol import schemas

    _, command = pcm_fixture(tmp_path)
    validator = Draft202012Validator(schemas()["agent.command.v1.schema.json"])
    envelope = {"version": 1, "owner": uuid4().hex, "command": command}
    assert list(validator.iter_errors(envelope)) == []
    old = deepcopy(envelope)
    old["command"]["agent"]["revision"] = "1"
    assert list(validator.iter_errors(old))
    missing = deepcopy(envelope)
    del missing["command"]["options"]["processing_profile"]
    assert list(validator.iter_errors(missing))
    gpu = deepcopy(envelope)
    gpu["command"]["options"]["vad_mode"] = "nvidia"
    assert list(validator.iter_errors(gpu))


def test_all_master_filter_thresholds_preserve_pcm_and_optional_off(tmp_path):
    cases = [
        ("conservative", 6, False),
        ("conservative", 12, True),
        ("strong", 4, False),
        ("strong", 6, True),
        ("silence3", 2, False),
        ("silence3", 4, True),
        ("off", 6, False),
    ]
    for index, (mode, silence, should_pack) in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        original, command = pcm_fixture(root, silence_seconds=silence)
        command["options"]["audio_filter"] = mode
        result = run(command, root, root / "outputs", agent="preprocess_audio")
        assert result["status"] == "completed", (mode, result)
        refs = result["outputs"]
        spans = json.loads(
            (root / "outputs" / refs["timeline"]["storage_key"]).read_bytes()
        )
        with wave.open(
            str(root / "outputs" / refs["audio"]["storage_key"]), "rb"
        ) as audio:
            packed = audio.readframes(audio.getnframes())
        expected = b"".join(
            original[
                round(s["source_start"] * 16000) * 2 : round(s["source_end"] * 16000)
                * 2
            ]
            for s in spans
        )
        assert packed == expected
        assert len(spans) == (2 if should_pack else 1)
        assert (len(packed) < len(original)) == should_pack


def test_old_cpu_revision_cannot_silently_activate_new_profile(tmp_path):
    _, command = pcm_fixture(tmp_path)
    command["agent"]["revision"] = "1"
    result = run(command, tmp_path, tmp_path / "outputs", agent="preprocess_audio")
    assert result["status"] == "failed" and result["outputs"] == {}


def test_new_profile_keeps_existing_clock_and_global_input_limits(tmp_path):
    import pytest
    from video_service.audio_clock import validate_clock
    from video_service.content_store import MAX_CONTENT
    from video_service.cpu_input_policy import input_limit

    _, command = pcm_fixture(tmp_path, silence_seconds=299)
    result = run(command, tmp_path, tmp_path / "outputs", agent="preprocess_audio")
    assert result["status"] == "failed" and result["outputs"] == {}
    assert MAX_CONTENT == 268435456
    assert input_limit(command["agent"], "audio", "audio") == MAX_CONTENT
    with pytest.raises(ValueError):
        validate_clock(
            [
                {
                    "source_start": 0,
                    "source_end": 301,
                    "packed_start": 0,
                    "packed_end": 301,
                }
            ]
        )
    for role in ["extract_audio", "encode", "analyze", "validate_video"]:
        with pytest.raises(ValueError):
            input_limit({"id": role, "revision": "3"}, "video", "video")


def test_new_profile_bounds_normalization_before_packing(tmp_path, monkeypatch):
    import video_service.cpu_agents as cpu

    original_process = cpu.process
    normalized_calls = []

    def observed(arguments, **kwargs):
        if arguments[-1].endswith("normalized.wav"):
            normalized_calls.append((arguments, kwargs))
        return original_process(arguments, **kwargs)

    monkeypatch.setattr(cpu, "process", observed)
    _, command = pcm_fixture(tmp_path)
    result = cpu.run(command, tmp_path, tmp_path / "outputs", agent="preprocess_audio")
    assert result["status"] == "completed", result
    args, kwargs = normalized_calls[0]
    assert "-t" in args and args[args.index("-t") + 1] == "301"
    assert kwargs["timeout"] == 30


def test_new_cpu_profile_is_not_a_nvidia_engine_alias():
    import pytest
    from video_service.node_contracts import validate_node

    with pytest.raises(ValueError, match="silence_pack_v3"):
        validate_node(
            {
                "node": "preprocess_audio",
                "inputs": {"audio": "audio"},
                "options": {
                    "processing_profile": "silence_pack_v3",
                    "audio_filter": "strong",
                    "vad_mode": "nvidia",
                },
            }
        )
