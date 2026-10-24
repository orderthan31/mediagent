"""Controlled VAD-child responses exercise contracts/PCM, NOT GPU inference."""

import hashlib
import importlib.util
import io
import json
import math
import struct
import sys
import wave
from pathlib import Path
from uuid import uuid4

from video_service.content_store import ContentStore
from video_service.engine_protocol import make_command

if importlib.util.find_spec("mideagent_gpu"):
    from mideagent_gpu import adapters
    from mideagent_gpu.vad import retained_intervals
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))
    from gpu import adapters
    from gpu.vad import retained_intervals


def fixture(tmp_path):
    owner = uuid4().hex
    (tmp_path / "store").mkdir()
    store = ContentStore(tmp_path / "store")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model = model_dir / "vad_multilingual_marblenet.nemo"
    model.write_bytes(b"synthetic non-model fixture; no inference")
    pcm = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
        for i in range(16000)
    )
    pcm = pcm + bytes(6 * 32000) + pcm
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    audio_ref = store.put(owner, [buf.getvalue()], "audio")
    runtime = {
        "role": "preprocess_audio",
        "family": "gpu",
        "engine": "nvidia-marblenet",
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "source_language": None,
        "target_language": None,
    }
    regions = {
        "version": 1,
        "source_sha256": audio_ref["sha256"],
        "source_frames": len(pcm) // 2,
        "protected": [{"start": 3, "end": 4}],
        "removals": [{"start": 0.5, "end": 0.7}, {"start": 0.9, "end": 3.1}],
    }
    region_ref = store.put(owner, [json.dumps(regions).encode()], "audio_regions")
    command = make_command(
        "preprocess_audio",
        run_id=uuid4().hex,
        attempt_id=uuid4().hex,
        generation=1,
        inputs={"audio": audio_ref, "regions": region_ref},
        options={
            "processing_profile": "nvidia_regions_v4",
            "vad_mode": "nvidia",
            "audio_filter": "strong",
        },
        runtime=runtime,
    )
    return (
        store,
        owner,
        command,
        {"descriptor": runtime, "model_dir": str(model_dir)},
        pcm,
    )


def test_explicit_nvidia_regions_intersects_after_protection_and_veto(
    tmp_path, monkeypatch
):
    store, owner, command, config, pcm = fixture(tmp_path)
    calls = []

    def controlled_child(argv, work):
        calls.append(argv)
        assert argv[argv.index("--device") + 1] == "cuda"
        probabilities = [1.0] * 100
        report = {
            "version": 2,
            "device": "cuda",
            "requested_device": "cuda",
            "cuda_peak_allocated_bytes": 1,
            "duration_seconds": 8.0,
            "model_sha256": command["runtime"]["model_sha256"],
            "probabilities": probabilities,
            "intervals": retained_intervals(probabilities, 8.0),
        }
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps(report))

    monkeypatch.setattr(adapters, "child", controlled_child)
    outputs = adapters.execute(store, owner, command, config)
    assert len(calls) == 1
    clock = json.loads(outputs["timeline"][0])
    spans = clock["spans"]
    # Speech veto with 0.3s padding cancels the WHOLE overlapping removal.
    assert any(s["source_start"] <= 2.7 and s["source_end"] >= 4.3 for s in spans)
    assert any(s["source_start"] <= 0.9 and s["source_end"] >= 1.2 for s in spans)
    assert not any(s["source_start"] < 0.7 and s["source_end"] > 0.5 for s in spans)
    expected = b"".join(
        pcm[round(s["source_start"] * 16000) * 2 : round(s["source_end"] * 16000) * 2]
        for s in spans
    )
    with wave.open(io.BytesIO(outputs["audio"][0]), "rb") as audio:
        assert audio.readframes(audio.getnframes()) == expected
    assert clock["audio_sha256"] == hashlib.sha256(outputs["audio"][0]).hexdigest()
    assert clock["source_sha256"] == command["inputs"]["audio"]["sha256"]


def test_no_retained_frames_is_failure_not_empty_success(tmp_path, monkeypatch):
    import pytest

    store, owner, command, config, _ = fixture(tmp_path)
    ref = command["inputs"]["regions"]
    doc = json.loads(store.read(owner, ref))
    doc["protected"] = []
    doc["removals"] = [{"start": 0, "end": 8}]
    command["inputs"]["regions"] = store.put(
        owner, [json.dumps(doc).encode()], "audio_regions"
    )

    def controlled_child(argv, work):
        Path(argv[argv.index("--output") + 1]).write_text(
            json.dumps(
                {
                    "version": 2,
                    "device": "cuda",
                    "requested_device": "cuda",
                    "cuda_peak_allocated_bytes": 1,
                    "duration_seconds": 8.0,
                    "model_sha256": command["runtime"]["model_sha256"],
                    "probabilities": [1.0] * 100,
                    "intervals": [[0.0, 8.0]],
                }
            )
        )

    monkeypatch.setattr(adapters, "child", controlled_child)
    with pytest.raises(ValueError, match="invalid_audio_clock"):
        adapters.execute(store, owner, command, config)


def test_cuda_claim_cannot_hide_cpu_requested_device(tmp_path, monkeypatch):
    import pytest

    store, owner, command, config, _ = fixture(tmp_path)

    def controlled_child(argv, work):
        Path(argv[argv.index("--output") + 1]).write_text(
            json.dumps(
                {
                    "version": 2,
                    "device": "cuda",
                    "requested_device": "cpu",
                    "cuda_peak_allocated_bytes": 1,
                    "duration_seconds": 8.0,
                    "model_sha256": command["runtime"]["model_sha256"],
                    "probabilities": [1.0] * 100,
                    "intervals": [[0.0, 8.0]],
                }
            )
        )

    monkeypatch.setattr(adapters, "child", controlled_child)
    with pytest.raises(ValueError, match="explicit_cuda_vad_report_required"):
        adapters.execute(store, owner, command, config)


def test_bad_region_source_pin_never_enters_cuda_child(tmp_path, monkeypatch):
    import pytest

    store, owner, command, config, _ = fixture(tmp_path)
    doc = json.loads(store.read(owner, command["inputs"]["regions"]))
    doc["source_sha256"] = "0" * 64
    command["inputs"]["regions"] = store.put(
        owner, [json.dumps(doc).encode()], "audio_regions"
    )
    calls = []
    monkeypatch.setattr(adapters, "child", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="source_pin_mismatch"):
        adapters.execute(store, owner, command, config)
    assert calls == []


def test_off_ignores_region_cuts_but_vad_is_still_intersected_last(
    tmp_path, monkeypatch
):
    store, owner, command, config, _ = fixture(tmp_path)
    command["options"]["audio_filter"] = "off"
    probabilities = [1.0] * 12 + [0.0] * 76 + [1.0] * 12
    retained = retained_intervals(probabilities, 8.0)

    def controlled_child(argv, work):
        Path(argv[argv.index("--output") + 1]).write_text(
            json.dumps(
                {
                    "version": 2,
                    "device": "cuda",
                    "requested_device": "cuda",
                    "cuda_peak_allocated_bytes": 1,
                    "duration_seconds": 8.0,
                    "model_sha256": command["runtime"]["model_sha256"],
                    "probabilities": probabilities,
                    "intervals": retained,
                }
            )
        )

    monkeypatch.setattr(adapters, "child", controlled_child)
    out = adapters.execute(store, owner, command, config)
    spans = json.loads(out["timeline"][0])["spans"]
    assert any(s["source_start"] <= 0.5 and s["source_end"] >= 0.7 for s in spans)
    assert not any(s["source_start"] < 4 and s["source_end"] > 3 for s in spans)


def test_forged_vad_interval_is_not_accepted_over_probabilities(tmp_path, monkeypatch):
    import pytest

    store, owner, command, config, _ = fixture(tmp_path)

    def controlled_child(argv, work):
        Path(argv[argv.index("--output") + 1]).write_text(
            json.dumps(
                {
                    "version": 2,
                    "device": "cuda",
                    "requested_device": "cuda",
                    "cuda_peak_allocated_bytes": 1,
                    "duration_seconds": 8.0,
                    "model_sha256": command["runtime"]["model_sha256"],
                    "probabilities": [1.0] * 100,
                    "intervals": [[1.0, 8.0]],
                }
            )
        )

    monkeypatch.setattr(adapters, "child", controlled_child)
    with pytest.raises(ValueError, match="probability_mismatch"):
        adapters.execute(store, owner, command, config)
