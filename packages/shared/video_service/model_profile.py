"""Declared model taxonomy, independent of agent task roles and live inference.

A registered declaration is not proof that an endpoint implements it. Old task-
role-only immutable revisions remain unclassified until explicitly superseded.
"""

MODEL_TYPES = {
    "text",
    "tts",
    "multimodal",
    "vision",
    "speech_recognition",
    "decision",
    "embedding",
    "image_generation",
    "video_generation",
}
MODALITIES = {"text", "audio", "image", "video", "vector"}
CAPABILITIES = {
    "text_generation",
    "speech_recognition",
    "speech_synthesis",
    "image_understanding",
    "structured_output",
    "embedding",
    "image_generation",
    "video_generation",
    "vocalization_classification",
}


def selection(value, allowed):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= len(allowed)
        or any(not isinstance(v, str) for v in value)
        or len(set(value)) != len(value)
        or not set(value) <= allowed
    ):
        raise ValueError("모델 유형·입출력·지원 기능을 올바르게 선택하세요.")
    return sorted(value)


def validate_profile(model_types, input_modalities, output_modalities, capabilities):
    result = {
        "model_types": selection(model_types, MODEL_TYPES),
        "input_modalities": selection(input_modalities, MODALITIES),
        "output_modalities": selection(output_modalities, MODALITIES),
        "capabilities": selection(capabilities, CAPABILITIES),
    }
    inputs, outputs, features = (
        set(result[k])
        for k in ("input_modalities", "output_modalities", "capabilities")
    )
    requirements = {
        "text_generation": ({"text"}, {"text"}),
        "structured_output": ({"text"}, {"text"}),
        "speech_recognition": ({"audio"}, {"text"}),
        "vocalization_classification": ({"audio"}, {"text"}),
        "speech_synthesis": ({"text"}, {"audio"}),
        "image_understanding": ({"image"}, {"text"}),
        "embedding": (set(), {"vector"}),
        "image_generation": (set(), {"image"}),
        "video_generation": (set(), {"video"}),
    }
    for feature in features:
        required_inputs, required_outputs = requirements[feature]
        if not required_inputs <= inputs or not required_outputs <= outputs:
            raise ValueError("지원 기능에 필요한 입력·출력 유형이 빠졌습니다.")
    required_features = {
        "text": "text_generation",
        "tts": "speech_synthesis",
        "speech_recognition": "speech_recognition",
        "vision": "image_understanding",
        "decision": "structured_output",
        "embedding": "embedding",
        "image_generation": "image_generation",
        "video_generation": "video_generation",
    }
    if any(
        feature not in features
        for kind, feature in required_features.items()
        if kind in result["model_types"]
    ):
        raise ValueError("모델 유형에 필요한 지원 기능이 빠졌습니다.")
    if "multimodal" in result["model_types"] and len(inputs | outputs) < 2:
        raise ValueError("멀티모달은 둘 이상의 자료 유형이 필요합니다.")
    return result


def supports_role(profile, role):
    if not profile.get("model_types"):
        return False
    inputs, outputs, features = (
        set(profile.get(k, []))
        for k in ("input_modalities", "output_modalities", "capabilities")
    )
    requirements = {
        "transcription": ("audio", "text", "speech_recognition"),
        "vocalization": ("audio", "text", "vocalization_classification"),
        "translation": ("text", "text", "text_generation"),
        "decision": ("text", "text", "structured_output"),
        "tts": ("text", "audio", "speech_synthesis"),
    }
    required = requirements.get(role)
    return bool(
        required
        and required[0] in inputs
        and required[1] in outputs
        and required[2] in features
    )


def supports_transcription(profile, protocol, model):
    """Declared timed-audio contract; never use an LLM name as eligibility.

    The SDK/provider must still accept the selected operation and the response
    must contain validated real timestamps. A declaration is not live readiness.
    """
    return bool(
        supports_role(profile, "transcription")
        and isinstance(model, str)
        and 1 <= len(model) <= 200
        and protocol in {"gemini", "openai", "openai_compatible"}
    )


def supports_vocalization(profile, protocol, model):
    """Explicit audio-event declaration plus implemented wire, NOT a provider probe."""
    import re

    return bool(
        supports_role(profile, "vocalization")
        and "structured_output" in profile.get("capabilities", [])
        and protocol == "gemini"
        and isinstance(model, str)
        and re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,190}", model)
    )
