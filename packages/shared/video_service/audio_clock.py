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
