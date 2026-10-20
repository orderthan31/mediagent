"""Bounded transcript parsing shared by independent agents."""

import json
import math

from .transcript import TranscriptSegment


def parse_segments(raw):
    try:
        values = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Transcript must be UTF-8 JSON") from None
    if not isinstance(values, list) or not 1 <= len(values) <= 10000:
        raise ValueError("Transcript must contain 1 to 10000 segments")
    result = []
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) - {"start", "end", "text", "speaker"}
            or not {"start", "end", "text"} <= set(value)
            or any(
                type(value[k]) not in (int, float) or not math.isfinite(value[k])
                for k in ("start", "end")
            )
            or not 0 <= value["start"] < value["end"]
            or not isinstance(value["text"], str)
            or not 1 <= len(value["text"]) <= 16000
            or (
                value.get("speaker") is not None
                and (
                    not isinstance(value["speaker"], str) or len(value["speaker"]) > 200
                )
            )
        ):
            raise ValueError("Invalid transcript segment")
        result.append(TranscriptSegment.from_dict(value))
    return result
