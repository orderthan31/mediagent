"""Explicit bounded transcript batching without widening the 100/16KB wire."""

import hashlib
from copy import deepcopy
from typing import NamedTuple

from .cpu_agents import canonical
from .transcript_input import parse_segments

MAX_BATCH_TRANSCRIPT_BYTES = 16 * 1024 * 1024


class TranscriptBatch(NamedTuple):
    chunk_index: int
    start: int
    end: int
    segments: list
    sha256: str


def validate_source(source):
    if not isinstance(source, list) or not 1 <= len(source) <= 10000:
        raise ValueError("번역 전체 자막은 1~10000구간 이내입니다.")
    if len(canonical(source)) > MAX_BATCH_TRANSCRIPT_BYTES:
        raise ValueError("분할 번역 전체 자막 용량 제한 초과")
    plain, identifiers = [], set()
    for row in source:
        if not isinstance(row, dict) or set(row) - {
            "id",
            "start",
            "end",
            "text",
            "speaker",
        }:
            raise ValueError("자막 필드 오류")
        if "id" in row:
            identifier = row["id"]
            if type(identifier) not in (str, int) or (
                isinstance(identifier, str)
                and (
                    not 1 <= len(identifier) <= 128
                    or any(ord(c) < 32 for c in identifier)
                )
            ):
                raise ValueError("자막 ID 형식 오류")
            identity = (type(identifier).__name__, identifier)
            if identity in identifiers:
                raise ValueError("자막 ID 중복")
            identifiers.add(identity)
        plain.append({key: value for key, value in row.items() if key != "id"})
    parse_segments(canonical(plain))
    previous = 0
    for row in source:
        if row["start"] < previous:
            raise ValueError("자막 순서/시각이 중복되거나 뒤섞였습니다.")
        previous = row["end"]
        if len(canonical([row])) > 16000:
            raise ValueError("단일 자막이 번역 16KB 상한을 초과했습니다.")
    return source


def split_transcript(source):
    # Validate even the last row before any first batch can trigger a paid call.
    validate_source(source)
    start, current, index = 0, [], 0
    for row in source:
        proposed = current + [row]
        if current and (len(proposed) > 100 or len(canonical(proposed)) > 16000):
            value = deepcopy(current)
            yield TranscriptBatch(
                index,
                start,
                start + len(value),
                value,
                hashlib.sha256(canonical(value)).hexdigest(),
            )
            start += len(current)
            index += 1
            current = []
        current.append(row)
    if current:
        value = deepcopy(current)
        yield TranscriptBatch(
            index,
            start,
            start + len(value),
            value,
            hashlib.sha256(canonical(value)).hexdigest(),
        )
