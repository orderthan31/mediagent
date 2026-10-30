"""Versioned subtitle track contracts; no provider, worker startup or filesystem settings."""

import hashlib
import math
import re

from video_service.canonical import canonical
from .subtitles import segment_subtitles, segments_to_srt
from .transcript import TranscriptSegment

TRACK_BYTES = 16 * 1024 * 1024
MANIFEST_BYTES = 128 * 1024
POLICY = {
    "id": "subtitle_tracks_v1",
    "max_tracks": 6,
    "max_additional_languages": 4,
    "track_bytes": TRACK_BYTES,
    "aggregate_track_bytes": 6 * TRACK_BYTES,
    "manifest_bytes": MANIFEST_BYTES,
    "max_cues_per_track": 10000,
    "review_text_characters": 1000,
    "review_lines": 2,
    "media_seconds": 21600,
    "rendered_file_bytes": TRACK_BYTES,
}


def language(value, *, auto=False):
    if auto and value == "auto":
        return value
    if (
        not isinstance(value, str)
        or len(value) > 64
        or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value)
        or value == "auto"
        and not auto
    ):
        raise ValueError("invalid_subtitle_language")
    return value


def names(options, ports):
    result = {
        "original": language(options.get("original_language"), auto=True),
        "translated": language(options.get("translated_language")),
    }
    for index in range(1, 5):
        key = "additional_" + str(index)
        if key in ports:
            code = language(options.get(key + "_language"))
            result["translated." + code] = code
        elif options.get(key + "_language"):
            raise ValueError("declared_subtitle_language_has_no_input")
    translated = [value.lower() for key, value in result.items() if key != "original"]
    if len(set(translated)) != len(translated):
        raise ValueError("translation_languages_must_be_unique")
    return result


def normalize(cues, *, language: str, duration, initial=False):
    globals()["language"](language, auto=True)
    if (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or not 0 < duration <= POLICY["media_seconds"]
    ):
        raise ValueError("invalid_subtitle_media_duration")
    if (
        not isinstance(cues, list)
        or not 1 <= len(cues) <= 10000
        or len(canonical(cues)) > TRACK_BYTES
    ):
        raise ValueError("subtitle_track_budget_exceeded")
    from .transcript_batches import validate_source

    validate_source(cues)
    previous = 0
    rows = []
    lineage = []
    identifiers = set()
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or set(cue) - {
            "id",
            "start",
            "end",
            "text",
            "speaker",
        }:
            raise ValueError("invalid_review_cue_fields")
        if any(type(cue.get(key)) not in (int, float) for key in ["start", "end"]):
            raise ValueError("invalid_review_time")
        segment = TranscriptSegment.from_dict(cue)
        if (
            not math.isfinite(segment.start)
            or not math.isfinite(segment.end)
            or not 0 <= segment.start < segment.end <= duration + 0.05
            or segment.start < previous - 0.001
            or not isinstance(cue.get("text"), str)
            or not segment.text.strip()
            or len(segment.text) > (16000 if initial else 1000)
            or not initial
            and len(segment.text.splitlines()) > 2
        ):
            raise ValueError("invalid_subtitle_review_cue")
        previous = segment.end
        pieces = segment_subtitles(
            [segment],
            line_width=24
            if language.split("-")[0] in {"auto", "ko", "ja", "zh"}
            else 42,
        )
        children = []
        for number, piece in enumerate(pieces):
            identity = (
                segment.id
                if len(pieces) == 1 and segment.id is not None
                else "subtitle-"
                + hashlib.sha256(
                    canonical(
                        {"parent": segment.to_dict(), "row": index, "part": number}
                    )
                ).hexdigest()[:32]
            )
            if (type(identity), identity) in identifiers:
                raise ValueError("duplicate_review_cue_id")
            identifiers.add((type(identity), identity))
            value = {**piece.to_dict(), "id": identity}
            rows.append(value)
            children.append({"id": identity, "start": piece.start, "end": piece.end})
        lineage.append(
            {"source_row": index, "literal_parent_id": segment.id, "children": children}
        )
    if len(rows) > 10000 or len(canonical(rows)) > TRACK_BYTES:
        raise ValueError("normalized_subtitle_budget_exceeded")
    # Preserve master's renderer refusal of overlapping/sub-millisecond cues.
    segments_to_srt([TranscriptSegment.from_dict(row) for row in rows])
    return rows, {"version": 1, "language": language, "rows": lineage}
