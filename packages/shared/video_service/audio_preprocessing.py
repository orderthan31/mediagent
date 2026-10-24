"""Opt-in CPU silence packing; v3 retains the existing 300-second clock bound.

Thresholds, -45 dB detection and 0.2-second padding match master media.py.
NVIDIA probabilities, protected/vocalization intervals and long clocks are not
silently approximated here. Copy only verified integer PCM-frame ranges.
"""

import re
import wave

from .audio_clock import validate_clock


def pack_silence(source, destination, mode, *, detect, max_seconds=300):
    minimums = {"conservative": 10, "strong": 5, "silence3": 3}
    if mode not in {"off", *minimums}:
        raise ValueError("unsupported_silence_filter")
    with wave.open(str(source), "rb") as audio:
        total = audio.getnframes()
        rate = audio.getframerate()
        if (audio.getnchannels(), audio.getsampwidth(), rate) != (1, 2, 16000):
            raise ValueError("silence_pack_requires_mono_pcm16_16k")
        if not 0 < total <= rate * max_seconds:
            raise ValueError("silence_pack_v3_requires_existing_300s_clock")
        duration = total / rate
        removed = []
        if mode != "off":
            minimum = minimums[mode]
            raw = detect(minimum)
            if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
                raise ValueError("invalid_silence_detection")
            start = None
            for line in raw.decode("utf-8", errors="strict").splitlines():
                match = re.search(r"silence_(start|end):\s*(-?[\d.]+)", line)
                if match is None:
                    continue
                value = min(duration, max(0.0, float(match[2])))
                if match[1] == "start":
                    start = value
                elif start is not None:
                    if value - start >= minimum:
                        removed.append((start + 0.2, value - 0.2))
                    start = None
            if start is not None and duration - start >= minimum:
                removed.append((start + 0.2, duration - 0.2))
        kept = []
        cursor = 0.0
        for start, end in sorted(removed):
            if start > cursor:
                kept.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < duration:
            kept.append((cursor, duration))
    return copy_regions(source, destination, kept, max_seconds=max_seconds)


def copy_regions(source, destination, intervals, *, max_seconds=300):
    """Copy chosen original-clock PCM frames without expanding old clock limits."""
    with wave.open(str(source), "rb") as audio:
        total, rate = audio.getnframes(), audio.getframerate()
        if (audio.getnchannels(), audio.getsampwidth(), rate) != (
            1,
            2,
            16000,
        ) or not 0 < total <= max_seconds * rate:
            raise ValueError("region_copy_requires_bounded_pcm")
        ranges = [(round(a * rate), round(b * rate)) for a, b in intervals]
        spans = []
        packed = 0
        for first, last in ranges:
            if not 0 <= first < last <= total:
                raise ValueError("invalid_silence_frame_range")
            count = last - first
            spans.append(
                {
                    "source_start": first / rate,
                    "source_end": last / rate,
                    "packed_start": packed / rate,
                    "packed_end": (packed + count) / rate,
                }
            )
            packed += count
        validate_clock(spans, max_packed_seconds=max_seconds)
        with wave.open(str(destination), "wb") as output:
            output.setparams(audio.getparams())
            for first, last in ranges:
                audio.setpos(first)
                remaining = last - first
                while remaining:
                    count = min(remaining, rate)
                    frames = audio.readframes(count)
                    if len(frames) != count * 2:
                        raise ValueError("incomplete_silence_source_frames")
                    output.writeframesraw(frames)
                    remaining -= count
            if output.getnframes() != packed:
                raise ValueError("silence_packing_frame_mismatch")
    return spans
