"""Verified timed subtitle originals; no video asset, FFmpeg or model is required."""
from copy import deepcopy
import math
from pathlib import Path

from .subtitle_import import MAX_TEXT, parse_srt, parse_sami

PROFILE = "subtitle_file_v1"
MIME = {"srt": "application/x-subrip", "sami": "application/x-sami"}
EXTENSIONS = {".srt": "srt", ".smi": "sami", ".sami": "sami"}


def policy():
    return {"id": "original_subtitle_v1", "max_source_bytes": MAX_TEXT, "encoding": "utf-8", "max_segments": 10000}


def source_format(filename):
    return EXTENSIONS.get(Path(filename).suffix.lower()) if isinstance(filename, str) else None


def read_rows(path, filename, *, maximum=MAX_TEXT):
    kind = source_format(filename)
    if kind is None or not 0 < path.stat().st_size <= maximum:
        raise ValueError("입력 한도 이내의 SRT·SMI 자막 파일을 선택하세요.")
    raw = path.read_bytes()
    if not 0 < len(raw) <= maximum:
        raise ValueError("자막 원본 크기를 확인하세요.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("SRT·SMI 자막은 UTF-8로 저장한 뒤 등록하세요.") from None
    return parse_srt(text, maximum=maximum) if kind == "srt" else parse_sami(text, maximum=maximum)


def probe(path, filename):
    rows = read_rows(path, filename)
    return {"kind": "subtitle", "format": source_format(filename),
            "duration": max(row["end"] for row in rows), "segments": len(rows)}


def asset_media(asset):
    metadata = asset.get("metadata", {})
    media = metadata.get("media") or {}
    if not isinstance(media, dict):
        raise ValueError("원본 자료 분류를 확인하세요.")
    if "subtitle_original_policy" not in metadata and media.get("kind") != "subtitle":
        return None
    if (metadata.get("registration_state") != "verified" or metadata.get("subtitle_original_policy") != policy()
            or not isinstance(media, dict) or set(media) != {"kind", "format", "duration", "segments"}
            or media.get("kind") != "subtitle" or media.get("format") not in MIME
            or metadata.get("media_type") != MIME[media["format"]]
            or type(asset.get("bytes")) is not int or not 0 < asset["bytes"] <= MAX_TEXT
            or type(media.get("duration")) not in (int, float) or not math.isfinite(media["duration"]) or media["duration"] <= 0
            or type(media.get("segments")) is not int or not 1 <= media["segments"] <= 10000):
        raise ValueError("검증된 시간 자막 원본을 선택하세요.")
    return deepcopy(media)
