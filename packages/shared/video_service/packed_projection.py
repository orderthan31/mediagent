"""Explicit bounded packed-clock projection; legacy envelope restoration is unchanged."""

import hashlib
from bisect import bisect_right

from .audio_clock import validate_clock
from .cpu_agents import canonical
from .transcript_input import parse_segments

MAX_BYTES = 16 * 1024 * 1024


def validate_projection_clock(spans, *, policy="packed_projection_v2"):
    if policy not in {"packed_projection_v2", "packed_projection_v5"}:
        raise ValueError("unsupported_projection_policy")
    maximum = 6 * 60 * 60 if policy == "packed_projection_v5" else 300
    duration = validate_clock(spans, max_packed_seconds=maximum)
    if spans[-1]["source_end"] > maximum:
        raise ValueError("projection_v2_budget_exceeded")
    if any(
        abs(number * 16000 - round(number * 16000)) > 1e-6
        for span in spans
        for number in span.values()
    ):
        raise ValueError("projection_requires_pcm_frame_clock")
    previous = 0
    for span in spans:
        source_start, source_end, packed_start, packed_end = [
            round(span[key] * 16000)
            for key in ["source_start", "source_end", "packed_start", "packed_end"]
        ]
        if (
            packed_start != previous
            or source_end - source_start != packed_end - packed_start
        ):
            raise ValueError("projection_clock_frame_gap_overlap_or_scale")
        previous = packed_end
    return duration


def project(segments, spans, *, policy="packed_projection_v2"):
    duration = validate_projection_clock(spans, policy=policy)
    parse_segments(canonical(segments))
    if len(canonical(segments)) > MAX_BYTES:
        raise ValueError("projection_v2_budget_exceeded")
    input_ids = [
        (type(row["id"]).__name__, row["id"]) for row in segments if "id" in row
    ]
    if len(input_ids) != len(set(input_ids)):
        raise ValueError("projection_duplicate_input_id")
    source_sha = hashlib.sha256(canonical(segments)).hexdigest()
    trace = {
        "version": 5 if policy == "packed_projection_v5" else 2,
        "policy": policy,
        "packed_transcript_sha256": source_sha,
        "timeline_spans_sha256": hashlib.sha256(canonical(spans)).hexdigest(),
        "rows": [],
    }
    output, seen, previous, size = [], set(), 0, 0
    ends = [span["packed_end"] for span in spans]
    for index, row in enumerate(segments):
        if row["start"] < previous or row["end"] > duration + 1e-8:
            raise ValueError("projection_transcript_outside_clock_or_overlapping")
        previous = row["end"]
        pieces = []
        for span_index in range(bisect_right(ends, row["start"]), len(spans)):
            span = spans[span_index]
            if span["packed_start"] >= row["end"]:
                break
            left, right = (
                max(row["start"], span["packed_start"]),
                min(row["end"], span["packed_end"]),
            )
            if right <= left:
                continue
            start = span["source_start"] + left - span["packed_start"]
            end = span["source_start"] + right - span["packed_start"]
            if pieces and abs(start - pieces[-1]["end"]) < 1e-8:
                pieces[-1]["end"] = end
                pieces[-1]["span_indices"].append(span_index)
            else:
                pieces.append(
                    {"start": start, "end": end, "span_indices": [span_index]}
                )
        entry = {
            "input_index": index,
            "packed_segment": dict(row),
            "text_policy": "repeat-full-sentence-on-each-piece"
            if len(pieces) > 1
            else "preserve-full-sentence",
            "pieces": [],
        }
        for piece_index, piece in enumerate(pieces):
            if round(piece["end"] * 1000) <= round(piece["start"] * 1000):
                entry["pieces"].append({**piece, "status": "dropped_submillisecond"})
                continue
            identifier = (
                row.get("id")
                if len(pieces) == 1 and "id" in row
                else "projection-"
                + hashlib.sha256(
                    canonical({"input_sha256": source_sha, "index": index})
                ).hexdigest()[:24]
                + "-"
                + str(piece_index)
            )
            identity = (type(identifier).__name__, identifier)
            if identity in seen:
                raise ValueError("projection_duplicate_output_id")
            seen.add(identity)
            projected = {
                **row,
                "start": piece["start"],
                "end": piece["end"],
                "id": identifier,
            }
            size += len(canonical(projected))
            if len(output) >= 10000 or size > MAX_BYTES:
                raise ValueError("projection_output_budget_exceeded")
            entry["pieces"].append(
                {
                    **piece,
                    "output_index": len(output),
                    "output_id": identifier,
                    "status": "emitted",
                }
            )
            output.append(projected)
        trace["rows"].append(entry)
    parse_segments(canonical(output))
    if len(canonical(trace)) > MAX_BYTES:
        raise ValueError("projection_trace_budget_exceeded")
    trace["output_transcript_sha256"] = hashlib.sha256(canonical(output)).hexdigest()
    return output, trace
