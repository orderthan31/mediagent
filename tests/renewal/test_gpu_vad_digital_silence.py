"""Postprocessing regression; controlled probabilities are not GPU inference."""

import importlib.util
import struct
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "actual_vad_source", Path(__file__).resolve().parents[2] / "tools/gpu/vad.py"
)
assert _spec is not None and _spec.loader is not None
vad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vad)


def test_exact_zero_guard_ends_hysteresis_without_replacing_neural_scores():
    # The real pinned model returned this bias on digitally silent windows.
    # Preserve that raw score rather than misreporting it as model confidence 0.
    pcm = struct.pack("<h", 1000) * 16000 + bytes(6 * 32000)
    pcm += struct.pack("<h", 1000) * 16000
    silence = vad.digital_silence_windows(pcm)
    raw = [0.2968016266822815 if silent else 0.99 for silent in silence]
    original = list(raw)
    assert vad.retained_intervals(raw, 8.0) == [(0, 8.0)]
    effective = vad.apply_digital_silence(raw, silence)
    kept = vad.retained_intervals(effective, 8.0)
    assert raw == original
    assert sum(end - start for start, end in kept) < 8
    assert kept[0][0] == 0 and kept[-1][1] == 8
    assert all(p == (0.0 if silent else prior)
               for p, prior, silent in zip(effective, raw, silence))


def test_low_amplitude_is_not_digital_silence():
    pcm = struct.pack("<h", 1) * (8 * 16000)
    silence = vad.digital_silence_windows(pcm)
    assert silence and not any(silence)
    raw = [0.2968016266822815] * len(silence)
    assert vad.apply_digital_silence(raw, silence) == raw


@pytest.mark.parametrize("raw,mask", [
    ([float("nan")], [True]),
    ([float("inf")], [True]),
    ([True], [True]),
    ([1.1], [True]),
    ([0.5], [1]),
    ([0.5], []),
])
def test_zero_guard_cannot_hide_malformed_model_output(raw, mask):
    with pytest.raises(ValueError):
        vad.apply_digital_silence(raw, mask)


@pytest.mark.parametrize("fault", ["effective", "count", "unknown_policy"])
def test_gpu_adapter_recomputes_exact_zero_guard_from_source_pcm(tmp_path, monkeypatch, fault):
    from test_nvidia_regions import adapters, fixture

    store, owner, command, config, pcm = fixture(tmp_path)
    silence = vad.digital_silence_windows(pcm)
    raw = [1.0] * len(silence)
    effective = vad.apply_digital_silence(raw, silence)
    report = {
        "version": 2, "device": "cuda", "requested_device": "cuda",
        "cuda_peak_allocated_bytes": 1, "duration_seconds": 8.0,
        "model_sha256": command["runtime"]["model_sha256"],
        "probabilities": effective, "raw_probabilities": raw,
        "probability_policy": "neural_exact_zero_v1",
        "digital_silence_windows": sum(silence),
        "intervals": vad.retained_intervals(effective, 8.0),
    }
    if fault == "effective":
        report["probabilities"] = raw
    elif fault == "count":
        report["digital_silence_windows"] += 1
    else:
        report["probability_policy"] = "unrecognized"

    def controlled_child(argv, work):
        import json
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps(report))

    monkeypatch.setattr(adapters, "child", controlled_child)
    with pytest.raises(ValueError, match="vad_probability_policy|vad_digital_silence"):
        adapters.execute(store, owner, command, config)


@pytest.mark.parametrize("pcm", [b"", b"\x00"])
def test_complete_nonempty_pcm16_required(pcm):
    with pytest.raises(ValueError):
        vad.digital_silence_windows(pcm)
