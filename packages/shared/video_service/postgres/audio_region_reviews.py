"""Source-bound audio region review contracts; save, confirm and execute are separate."""

import wave

from ..audio_regions import region_intervals
from ..cpu_agents import canonical

KIND = "audio_regions_v1"


def contract_for(store, owner, source):
    if source["type"] != "audio":
        raise ValueError("audio_region_review_requires_audio")
    path = store.path(owner, source)
    with wave.open(str(path), "rb") as stream:
        frames = stream.getnframes()
        if (
            (stream.getnchannels(), stream.getsampwidth(), stream.getframerate())
            != (1, 2, 16000)
            or not 0 < frames <= 16000 * 300
            or len(stream.readframes(frames)) != frames * 2
        ):
            raise ValueError("audio_region_review_requires_bounded_pcm")
    return {
        "version": 2,
        "kind": KIND,
        "type": "audio",
        "source": source,
        "phase": "gate",
        "audio": {
            "source_sha256": source["sha256"],
            "source_frames": frames,
            "sample_rate": 16000,
            "duration_seconds": frames / 16000,
        },
        "fields": {
            "type": "object",
            "title": "음성 보호·제거 구간",
            "properties": {
                "protected": interval_field("보호 구간", frames / 16000),
                "removals": interval_field("제거 구간", frames / 16000, removal=True),
                "approved": {"type": "boolean", "title": "보호·제거 구간을 확인했음"},
            },
            "required": ["protected", "removals", "approved"],
        },
    }


def document_for(contract, draft):
    if (
        not isinstance(draft, dict)
        or set(draft) != {"approved", "protected", "removals"}
        or type(draft["approved"]) is not bool
    ):
        raise ValueError("invalid_audio_region_review_draft")
    if (
        not isinstance(draft["protected"], list)
        or not isinstance(draft["removals"], list)
        or any(
            not isinstance(row, dict) or set(row) != {"start", "end"}
            for row in draft["protected"]
        )
        or any(
            not isinstance(row, dict) or set(row) != {"start", "end", "kind"}
            for row in draft["removals"]
        )
    ):
        raise ValueError("invalid_audio_region_review_fields")
    document = {
        "version": 1,
        "source_sha256": contract["audio"]["source_sha256"],
        "source_frames": contract["audio"]["source_frames"],
        "protected": draft["protected"],
        "removals": draft["removals"],
    }
    if len(canonical(document)) > 131072:
        raise ValueError("audio_region_review_size_exceeded")
    region_intervals(
        [],
        document,
        source_sha256=contract["source"]["sha256"],
        source_frames=contract["audio"]["source_frames"],
        audio_filter="off",
        vad=[],
    )
    return document


def interval_field(title, duration, *, removal=False):
    properties = {
        key: {
            "type": "number",
            "title": label,
            "format": "seconds",
            "minimum": 0,
            "maximum": duration,
            "default": 0 if key == "start" else min(0.1, duration),
        }
        for key, label in [("start", "시작"), ("end", "끝")]
    }
    if removal:
        properties["kind"] = {
            "type": "string",
            "title": "제거 소리",
            "choices": [
                {"value": "breath", "label": "숨소리"},
                {"value": "grunt", "label": "힘주는 소리"},
            ],
            "default": "breath",
        }
    return {
        "type": "array",
        "title": title,
        "format": "audio-regions",
        "minItems": 0,
        "maxItems": 1024,
        "items": {
            "type": "object",
            "title": "원본 시각 구간",
            "properties": properties,
            "required": list(properties),
            "order": {
                "from": "start",
                "to": "end",
                "message": "끝 시각은 시작보다 커야 합니다.",
            },
        },
    }
