"""Apply explicitly supplied original-clock region decisions in legacy order.

This consumes decisions; it does not fabricate vocal-event detection or provider
confirmation. A padded protected region vetoes an entire overlapping removal.
NVIDIA retained regions are intersected LAST, including when filtering is off.
"""

import math


def region_intervals(
    kept, document, *, source_sha256, source_frames, audio_filter, vad
):
    duration = source_frames / 16000
    if document is None:
        protected, removals = [], []
    else:
        if (
            not isinstance(document, dict)
            or set(document)
            != {"version", "source_sha256", "source_frames", "protected", "removals"}
            or type(document["version"]) is not int
            or document["version"] != 1
            or document["source_sha256"] != source_sha256
            or type(document["source_frames"]) is not int
            or document["source_frames"] != source_frames
        ):
            raise ValueError("audio_regions_source_pin_mismatch")
        protected, removals = document["protected"], document["removals"]
        for values in [protected, removals]:
            if not isinstance(values, list) or len(values) > 1024:
                raise ValueError("audio_regions_count_exceeded")
            for row in values:
                if (
                    not isinstance(row, dict)
                    or not {"start", "end"} <= set(row)
                    or set(row) - {"start", "end", "kind"}
                    or any(
                        type(row[k]) not in (int, float) or not math.isfinite(row[k])
                        for k in ["start", "end"]
                    )
                    or not 0 <= row["start"] < row["end"] <= duration
                    or "kind" in row
                    and row["kind"] not in {"breath", "grunt"}
                ):
                    raise ValueError("invalid_audio_region")
    intervals = list(kept)
    if audio_filter != "off":
        padded = [
            (max(0, row["start"] - 0.3), min(duration, row["end"] + 0.3))
            for row in protected
        ]
        merged = []
        for left, right in sorted([*intervals, *padded]):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        cuts = sorted(
            (row["start"], row["end"])
            for row in removals
            if not any(row["start"] < b and row["end"] > a for a, b in padded)
        )
        intervals = []
        for left, right in merged:
            cursor = left
            for start, end in cuts:
                if end <= cursor:
                    continue
                if start >= right:
                    break
                if start > cursor:
                    intervals.append((cursor, min(start, right)))
                cursor = min(right, max(cursor, end))
            if cursor < right:
                intervals.append((cursor, right))
    return [
        (max(a, c), min(b, d))
        for a, b in intervals
        for c, d in vad
        if min(b, d) > max(a, c)
    ]
