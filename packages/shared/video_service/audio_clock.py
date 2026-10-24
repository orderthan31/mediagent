"""Map packed speech segment boundaries to the preserved source-media clock."""

import json
import math

from .transcript_input import parse_segments


def validate_clock(spans):
    if not isinstance(spans, list) or not 1 <= len(spans) <= 4096:
        raise ValueError("invalid_audio_clock")
    previous_source = previous_packed = 0.0
    for span in spans:
        if not isinstance(span, dict) or set(span) != {
            "source_start",
            "source_end",
            "packed_start",
            "packed_end",
        }:
            raise ValueError("invalid_audio_clock")
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in span.values()
        ):
            raise ValueError("invalid_audio_clock")
        start, end, packed, stop = (
            span[key]
            for key in ["source_start", "source_end", "packed_start", "packed_end"]
        )
        if (
            start < previous_source
            or end <= start
            or abs(packed - previous_packed) > 1 / 16000
            or stop <= packed
            or abs((end - start) - (stop - packed)) > 1 / 16000
            or end > 86400
            or stop > 300
        ):
            raise ValueError("non_monotonic_audio_clock")
        previous_source, previous_packed = end, stop
    return previous_packed


def restore_clock(segments, spans):
    previous_packed = validate_clock(spans)
    parse_segments(json.dumps(segments).encode())

    def mapped(time, *, end):
        if time < 0 or time > previous_packed + 0.05:
            raise ValueError("transcript_outside_audio_clock")
        time = min(time, previous_packed)
        for span in spans:
            if time < span["packed_end"] or end and time <= span["packed_end"]:
                return min(
                    span["source_end"],
                    span["source_start"] + max(0, time - span["packed_start"]),
                )
        return spans[-1]["source_end"]

    values = [
        {
            **row,
            "start": mapped(row["start"], end=False),
            "end": mapped(row["end"], end=True),
        }
        for row in segments
    ]
    parse_segments(json.dumps(values).encode())
    return values


def registered_clock(value, *, audio_sha256):
    """Bind only the explicit NVIDIA-regions clock; retain legacy list semantics."""
    if isinstance(value, list):
        validate_clock(value)
        return value
    import re

    if (
        not isinstance(value, dict)
        or set(value) != {"version", "audio_sha256", "source_sha256", "spans", "engine"}
        or type(value["version"]) is not int
        or value["version"] != 2
        or value["audio_sha256"] != audio_sha256
        or not isinstance(value["source_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["source_sha256"])
    ):
        raise ValueError("nvidia_clock_audio_pin_mismatch")
    engine = value["engine"]
    if (
        not isinstance(engine, dict)
        or engine.get("processing_profile") != "nvidia_regions_v4"
        or type(engine.get("source_frames")) is not int
        or not 0 < engine["source_frames"] <= 300 * 16000
        or type(engine.get("duration_seconds")) not in (int, float)
        or engine["duration_seconds"] != engine["source_frames"] / 16000
    ):
        raise ValueError("unsupported_nvidia_clock_contract")
    spans = value["spans"]
    validate_clock(spans)
    if spans[-1]["source_end"] > engine["duration_seconds"]:
        raise ValueError("nvidia_clock_outside_source_frames")
    if any(
        abs(number * 16000 - round(number * 16000)) > 1e-6
        for span in spans
        for number in span.values()
    ):
        raise ValueError("nvidia_clock_requires_pcm_frame_boundary")
    return spans
