"""Explicit whole-input audio batching; existing 60s/2MiB wire stays unchanged."""

import hashlib
import io
import wave
from typing import NamedTuple

from .audio_contract import MAX_AUDIO_SECONDS

MAX_BATCH_AUDIO_BYTES = 1024 * 1024 * 1024
MAX_BATCH_AUDIO_SECONDS = 6 * 60 * 60
RATE = 16000


class AudioBatch(NamedTuple):
    chunk_index: int
    start: float
    end: float
    audio: bytes
    sha256: str


def split_normalized_audio(raw):
    """Validate all input before yielding any provider-sized PCM16 WAV batch."""
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= MAX_BATCH_AUDIO_BYTES:
        raise ValueError("긴 음성은 PCM WAV 1GiB/6시간 이내입니다.")
    try:
        with wave.open(io.BytesIO(raw), "rb") as source:
            frames = source.getnframes()
            if (
                source.getnchannels(),
                source.getsampwidth(),
                source.getframerate(),
                source.getcomptype(),
            ) != (1, 2, RATE, "NONE"):
                raise ValueError("긴 전사는 mono/16kHz/PCM16 WAV가 필요합니다.")
            if not 0 < frames <= RATE * MAX_BATCH_AUDIO_SECONDS:
                raise ValueError("긴 음성 길이 제한을 초과했습니다.")
            pcm = source.readframes(frames + 1)
            if len(pcm) != frames * 2:
                raise ValueError("음성 길이/본문이 일치하지 않습니다.")
    except (wave.Error, EOFError):
        raise ValueError("검증 가능한 전체 PCM WAV가 필요합니다.") from None
    window = RATE * MAX_AUDIO_SECONDS
    for index, start in enumerate(range(0, frames, window)):
        end = min(frames, start + window)
        output = io.BytesIO()
        with wave.open(output, "wb") as part:
            part.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            part.writeframes(pcm[start * 2 : end * 2])
        audio = output.getvalue()
        yield AudioBatch(
            index, start / RATE, end / RATE, audio, hashlib.sha256(audio).hexdigest()
        )
