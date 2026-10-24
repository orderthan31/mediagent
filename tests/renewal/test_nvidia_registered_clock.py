"""Registered ASR accepts only the new explicitly pinned NVIDIA clock wrapper."""

import hashlib

import pytest
from video_service import audio_clock


def test_new_nvidia_clock_binds_audio_before_registered_asr():
    sha = hashlib.sha256(b"packed fixture").hexdigest()
    spans = [
        {"source_start": 2.0, "source_end": 3.0, "packed_start": 0, "packed_end": 1.0}
    ]
    wrapper = {
        "version": 2,
        "audio_sha256": sha,
        "source_sha256": "a" * 64,
        "spans": spans,
        "engine": {
            "processing_profile": "nvidia_regions_v4",
            "source_frames": 80000,
            "duration_seconds": 5.0,
        },
    }
    binder = getattr(audio_clock, "registered_clock", None)
    assert callable(binder), "explicit NVIDIA clock binding is not connected"
    assert binder(wrapper, audio_sha256=sha) == spans
    assert binder(spans, audio_sha256=sha) == spans
    with pytest.raises(ValueError):
        binder(wrapper, audio_sha256="b" * 64)
    wrapper["engine"]["processing_profile"] = "legacy_v1"
    with pytest.raises(ValueError):
        binder(wrapper, audio_sha256=sha)


def test_nvidia_wrapper_rejects_non_pcm_frame_boundary():
    spans = [
        {
            "source_start": 2.000001,
            "source_end": 3.0,
            "packed_start": 0,
            "packed_end": 1.0,
        }
    ]
    wrapper = {
        "version": 2,
        "audio_sha256": "b" * 64,
        "source_sha256": "a" * 64,
        "spans": spans,
        "engine": {
            "processing_profile": "nvidia_regions_v4",
            "source_frames": 80000,
            "duration_seconds": 5.0,
        },
    }
    with pytest.raises(ValueError, match="frame_boundary"):
        audio_clock.registered_clock(wrapper, audio_sha256="b" * 64)
