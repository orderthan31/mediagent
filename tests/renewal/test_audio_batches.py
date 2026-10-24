"""Explicit long-audio preparation; no provider calls and no short-contract widening."""

import hashlib
import io
import wave

import pytest

try:
    from video_service.audio_batches import split_normalized_audio
except ModuleNotFoundError as error:
    if error.name != "video_service.audio_batches":
        raise
    split_normalized_audio = None


def wav(seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x01" * (16000 * seconds))
    return output.getvalue()


def test_long_audio_uses_exact_frame_batches_with_the_original_clock_offsets():
    assert callable(split_normalized_audio)
    source = wav(121)
    batches = list(split_normalized_audio(source))
    assert [(item.start, item.end) for item in batches] == [
        (0, 60),
        (60, 120),
        (120, 121),
    ]
    frames = []
    from video_service.audio_contract import audio_info

    for item in batches:
        assert audio_info(item.audio)["duration_seconds"] == item.end - item.start
        assert hashlib.sha256(item.audio).hexdigest() == item.sha256
        with wave.open(io.BytesIO(item.audio), "rb") as audio:
            frames.append(audio.readframes(audio.getnframes()))
    with wave.open(io.BytesIO(source), "rb") as audio:
        assert b"".join(frames) == audio.readframes(audio.getnframes())
    with pytest.raises(ValueError):
        audio_info(source)
