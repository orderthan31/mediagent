"""Offline capability evidence from the pinned SDK, not application model names."""
from functools import lru_cache
import importlib.metadata
import json


@lru_cache(maxsize=1)
def capability_map():
    try:
        dist = importlib.metadata.distribution("litellm")
        if dist.version != "1.106.6":
            return {}
        path = dist.locate_file("litellm/model_prices_and_context_window_backup.json")
        return json.loads(path.read_text(encoding="utf8"))
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        return {}


def model_info(provider, model):
    data = capability_map()
    for key in (provider + "/" + model, model):
        info = data.get(key)
        namespaces = {provider, 'vertex_ai-language-models'} if provider == 'vertex_ai' else {provider}
        if isinstance(info, dict) and info.get("litellm_provider") in namespaces:
            return info
    return None


def sdk_profile(provider, model):
    info = model_info(provider, model)
    if not info or info.get("mode") not in ({"chat", "completion"} if provider == 'vertex_ai' else {"chat", "completion", "audio_transcription"}):
        return None
    source = info.get("source")
    evidence = ["https://github.com/BerriAI/litellm/blob/v1.106.6/model_prices_and_context_window.json"]
    if isinstance(source, str) and source.startswith("https://"):
        evidence.append(source)
    variants = {}
    if info["mode"] == "audio_transcription":
        profile = {"model_types": ["speech_recognition"], "input_modalities": ["audio"], "output_modalities": ["text"], "capabilities": ["speech_recognition"]}
    else:
        inputs, types, features = ["text"], ["text"], ["text_generation"]
        if info.get("supports_vision"):
            inputs.append("image"); types.append("vision"); features.append("image_understanding")
        if info.get("supports_response_schema"):
            features.append("structured_output")
        profile = {"model_types": types, "input_modalities": inputs, "output_modalities": ["text"], "capabilities": features}
        audio_input = info.get("supports_audio_input") is True or (provider == 'vertex_ai' and isinstance(info.get('supported_modalities'), list) and 'audio' in info['supported_modalities'])
        if audio_input and info.get("supports_response_schema"):
            variant = {"model_types": sorted(set(types + ["multimodal"])), "input_modalities": sorted(set(inputs + ["audio"])),
                       "output_modalities": ["text"], "capabilities": sorted(set(features + ["speech_recognition"]))}
            audio_evidence = evidence + (["https://ai.google.dev/gemini-api/docs/generate-content/audio"] if provider == "gemini" else [])
            variants["transcription"] = {"profile": variant, "evidence": audio_evidence,
                                         "reason": "SDK 메타데이터의 음성 입력·구조화 응답 계약입니다. 실제 전사·시각·품질은 미검증입니다."}
    return {"profile": profile, "profile_variants": variants, "evidence": evidence}
