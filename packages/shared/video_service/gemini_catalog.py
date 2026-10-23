"""Curated primary capability evidence intersected with the installed text adapter.

Catalogs remain live/discovered. This table is not a provider-model dropdown and
never asserts inference, price/quality, or timestamped audio support.
"""

from copy import deepcopy

_DOC_ROOT = "https://ai.google.dev/gemini-api/docs/models/"
_LEGACY = {"gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"}
_TEXT_MODELS = {
    model: _DOC_ROOT + model
    for model in (
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-4-argon",
    )
}
_TEXT_MODELS["gemini-3.1-pro-preview-customtools"] = (
    _DOC_ROOT + "gemini-3.1-pro-preview"
)
_TEXT_PROFILE = {
    "model_types": ["text"],
    "capabilities": ["text_generation"],
    "input_modalities": ["text"],
    "output_modalities": ["text"],
}
_LEGACY_PROFILE = {
    "model_types": ["text", "vision", "multimodal"],
    "capabilities": ["image_understanding", "text_generation"],
    "input_modalities": ["audio", "image", "text", "video"],
    "output_modalities": ["text"],
}


def classify_gemini(item, catalog_items=None):
    model = item["id"]
    methods = item.get("supportedGenerationMethods") or []
    unsupported = None
    image_ids = {
        "gemini-2.5-flash-image",
        "gemini-3-pro-image",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image",
    }
    tts_ids = {
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
        "gemini-3.1-flash-tts-preview",
        "gemini-3.8-flash-tts",
        "gemini-3.8-flash-lite-tts",
    }
    if model == "gemini-3.1-flash-lite-preview":
        unsupported = (
            "종료 표기 프리뷰",
            _DOC_ROOT.rstrip("/"),
            "공식 목록 안내에서 종료로 표기된 프리뷰입니다. 공급자 목록에 남아 있어도 신규 실행 후보로 자동 등록하지 않습니다.",
        )
    elif model in image_ids:
        unsupported = (
            "이미지 생성",
            _DOC_ROOT.rstrip("/"),
            "공식 이미지 생성 모델입니다. 현재 제품의 텍스트 번역/타임스탬프 전사 어댑터 등록 후보가 아닙니다.",
        )
    elif model in tts_ids:
        unsupported = (
            "음성 생성 (TTS)",
            _DOC_ROOT.rstrip("/"),
            "공식 음성 생성 모델입니다. 현재 제품의 번역/타임스탬프 전사 연결은 지원하지 않습니다.",
        )
    elif model == "gemini-3.5-transcribe":
        unsupported = (
            "음성 전사 (단어 타임스탬프)",
            _DOC_ROOT + "gemini-3.5-transcribe",
            "제공사의 전사/타임스탬프 기능은 알려져 있으나 현재 등록 전사 어댑터의 요청/응답 형식 연결은 검증·구현되지 않아 선택 대상에서 제외합니다.",
        )
    elif isinstance(methods, list) and "generateContent" not in methods:
        if "embedContent" in methods:
            unsupported = (
                "임베딩",
                _DOC_ROOT.rstrip("/"),
                "목록의 embedContent 전용 모델입니다. 현재 번역/전사 어댑터가 처리하는 요청이 아닙니다.",
            )
        elif "bidiGenerateContent" in methods:
            unsupported = (
                "Live 스트리밍",
                _DOC_ROOT.rstrip("/"),
                "목록의 양방향 스트리밍 전용 모델입니다. 현재 단발 번역/전사 어댑터와 다릅니다.",
            )
        elif "predict" in methods or "predictLongRunning" in methods:
            unsupported = (
                "별도 predict 생성 API",
                _DOC_ROOT.rstrip("/"),
                "목록의 predict 계열 전용 API입니다. 현재 번역/전사 어댑터 연결은 지원하지 않습니다.",
            )
    if unsupported:
        purpose, evidence, reason = unsupported
        return {
            "profile": None,
            "classification_status": "unsupported",
            "provider_purpose": purpose,
            "reason": reason,
            "evidence": [evidence],
        }
    aliases = {
        "gemini-pro-latest": {"gemini-2.5-pro", "gemini-3.1-pro-preview"},
        "gemini-flash-latest": {
            "gemini-2.5-flash",
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
        },
        "gemini-flash-lite-latest": {
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
        },
    }
    if model in aliases and isinstance(methods, list) and "generateContent" in methods:
        # Official SDK literals and the actual descriptor identify the variation,
        # not a particular underlying model. Never manufacture a target from version.
        descriptors = {
            "gemini-flash-latest": (
                "Gemini Flash Latest",
                "Latest release of Gemini Flash",
            ),
            "gemini-flash-lite-latest": (
                "Gemini Flash-Lite Latest",
                "Latest release of Gemini Flash-Lite",
            ),
            "gemini-pro-latest": ("Gemini Pro Latest", "Latest release of Gemini Pro"),
        }
        title, description = descriptors[model]
        if (
            item.get("name") == "models/" + model
            and item.get("version") == title
            and item.get("displayName") == title
            and item.get("description") == description
        ):
            return {
                "profile": deepcopy(_TEXT_PROFILE),
                "classification_status": "supported",
                "provider_purpose": "텍스트 생성 (latest 별칭)",
                "reason": "공식 SDK의 latest 변형 별칭과 실제 목록 설명을 대조한 최소 텍스트 번역 후보입니다. version은 사람이 읽는 라벨이며 기반 모델은 미고정입니다. 제공사가 대상을 바꿀 수 있고 실제 실행은 미검증입니다.",
                "evidence": [
                    _DOC_ROOT.rstrip("/"),
                    "https://github.com/googleapis/python-genai/blob/main/google/genai/_gaos/types/interactions/model.py",
                ],
            }
        version = item.get("version")
        witnesses = {
            row["id"]
            for row in (catalog_items or [])
            if row.get("id") in aliases[model]
            and isinstance(version, str)
            and version
            and row.get("version") == version
            and "generateContent" in row.get("supportedGenerationMethods", [])
        }
        if len(witnesses) == 1:
            basis = next(iter(witnesses))
            return {
                "profile": deepcopy(_TEXT_PROFILE),
                "classification_status": "supported",
                "provider_purpose": "텍스트 생성 (latest 별칭)",
                "reason": "latest 별칭입니다. 같은 실제 목록의 version과 공식 텍스트 모델 근거를 대조했습니다. 제공사가 별칭 대상을 바꿀 수 있으며 실행 성공은 미확인입니다.",
                "evidence": [_TEXT_MODELS[basis], _DOC_ROOT.rstrip("/")],
                "catalog_version_witness": basis,
            }
    if (
        model in _TEXT_MODELS
        and isinstance(methods, list)
        and "generateContent" in methods
    ):
        reason = "공식 텍스트 출력 근거와 현재 텍스트 어댑터의 번역 후보입니다. 추론·품질 확인은 아닙니다."
        provider_routes = {
            "gemini-3.5-flash": "gemini-3.6-flash",
            "gemini-3.7-flash": "gemini-3.8-flash",
        }
        if model in provider_routes:
            reason += (
                " 제공사 문서상 "
                + provider_routes[model]
                + "로 자동 라우팅됩니다. 저장/요청 모델 ID는 바꾸지 않으며 기반 모델 고정으로 해석하지 마세요."
            )
        return {
            "profile": deepcopy(_LEGACY_PROFILE if model in _LEGACY else _TEXT_PROFILE),
            "classification_status": "supported",
            "provider_purpose": "텍스트 생성",
            "reason": reason,
            "evidence": [_TEXT_MODELS[model]],
        }
    return {
        "profile": None,
        "classification_status": "unknown",
        "provider_purpose": "",
        "reason": "실제 목록에는 있으나 현재 어댑터와 용도 근거의 교집합을 확인하지 못했습니다.",
        "evidence": [],
    }
