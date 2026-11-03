"""Versioned invocation settings frozen from a workflow, not an LLM allowlist.

This is a new-request contract. Missing contracts on historical candidates keep
legacy execution semantics; no saved model revision or snapshot is rewritten.
"""
from copy import deepcopy
import json
import math

from .model_profile import supports_role

SDK_PROTOCOLS = {"openai": "openai", "openai_compatible": "openai", "gemini": "gemini", "anthropic": "anthropic"}
ROLES = {"transcribe": "transcription", "transcription_agent": "transcription", "translate": "translation", "translation_agent": "translation", "vocalize": "vocalization"}


def parse_options(raw=""):
    if not isinstance(raw, str) or len(raw.encode()) > 2048:
        raise ValueError("모델 요청 옵션은 2KB 이내의 JSON 객체여야 합니다.")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("중복 모델 요청 옵션입니다.")
                result[key] = value
            return result
        value = json.loads(raw or "{}", object_pairs_hook=unique)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("모델 요청 옵션의 JSON 형식을 확인하세요.") from None
    bounds = {"temperature": (0, 2), "top_p": (0, 1), "max_tokens": (1, 16384), "timeout": (1, 120), "seed": (0, 2147483647)}
    if not isinstance(value, dict) or set(value) - set(bounds) - {"audio_api", "reasoning_effort"}:
        raise ValueError("지원하지 않는 모델 요청 옵션입니다. 모델·키·주소·재시도는 덮어쓸 수 없습니다.")
    for key, item in value.items():
        if key in bounds:
            if type(item) not in (int, float) or not math.isfinite(item) or not bounds[key][0] <= item <= bounds[key][1] or key in {"max_tokens", "seed"} and type(item) is not int:
                raise ValueError("모델 요청 옵션의 값 범위를 확인하세요.")
        elif key == "audio_api" and item not in {"structured_audio", "audio_transcription"}:
            raise ValueError("지원되는 시간 정보 전사 요청 방식을 선택하세요.")
        elif key == "reasoning_effort" and item not in {"low", "medium", "high"}:
            raise ValueError("지원되는 추론 강도를 선택하세요.")
    return value


def validate_operation_options(operation, options):
    if operation == "audio_transcription":
        unsupported = set(options) - {"audio_api", "timeout", "temperature"}
        if unsupported:
            raise ValueError("이 시간 정보 전사 API가 지원하지 않는 옵션입니다: " + ", ".join(sorted(unsupported)))


def freeze_inference(row, role, raw_options=""):
    role = ROLES.get(role, role)
    options = parse_options(raw_options)
    protocol = row["protocol"]
    model = row["remote_model"]
    if protocol not in SDK_PROTOCOLS or not supports_role(row, role):
        raise ValueError("선택한 모델의 입력·출력·업무 기능을 확인하세요.")
    if not isinstance(model, str) or not 1 <= len(model) <= 200 or any(ord(c) < 33 for c in model):
        raise ValueError("등록된 모델 ID 형식을 확인하세요.")
    if role == "transcription":
        operation = options.get("audio_api") or ("structured_audio" if {"text_generation", "structured_output"} <= set(row["capabilities"]) else "audio_transcription")
        if operation == "structured_audio" and "structured_output" not in row["capabilities"]:
            raise ValueError("음성 JSON 전사에는 구조화 응답 기능이 필요합니다.")
        if protocol == "anthropic":
            raise ValueError("현재 SDK의 이 공급자 경로는 음성 입력·시간 정보 전사를 지원하지 않습니다.")
    elif role == "translation":
        operation = "translation"
        if "audio_api" in options:
            raise ValueError("번역에는 음성 API 옵션을 지정할 수 없습니다.")
    else:
        raise ValueError("이 업무의 SDK 호출 계약은 아직 연결되지 않았습니다.")
    validate_operation_options(operation, options)
    return {"version": 1, "adapter": "litellm", "provider": SDK_PROTOCOLS[protocol], "connection_provider": row.get("provider", protocol), "model": model,
            "model_id": row["model_id"], "revision": row["revision"], "role": role, "operation": operation, "options": deepcopy(options)}


def validate_inference(row, contract):
    if not isinstance(contract, dict):
        raise ValueError("고정 모델 호출 계약이 없습니다.")
    expected = freeze_inference(row, contract.get("role"), json.dumps(contract.get("options"), allow_nan=False))
    if expected != contract:
        raise ValueError("고정 모델 호출 계약이 등록 버전과 다릅니다.")
    return expected
