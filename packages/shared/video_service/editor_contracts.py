"""Derive execution-only defaults for new business-only editor nodes, preserving pins."""

from copy import deepcopy


def resolve_editor_contracts(payload):
    result = deepcopy(payload)
    nodes = result.get("nodes", [])
    long_mode = any(
        n.get("options", {}).get("media_budget") == "audio_long_v5"
        or n["type"] == "transcribe"
        and "batch_policy" not in n.get("options", {})
        for n in nodes
    )
    for node in nodes:
        role = node["type"]
        options = node.setdefault("options", {})
        if role == "transcribe" and "batch_policy" not in options:
            options.update(
                batch_policy="bounded_60s_v1",
                clock_policy="packed_projection_v5",
                media_budget="audio_long_v5",
                max_model_calls="128",
            )
        if role == "translate" and "batch_policy" not in options:
            options.update(batch_policy="bounded_100x16k_v1", max_model_calls="128")
            if long_mode:
                options.setdefault("media_budget", "audio_long_v5")
        if role == "translate" and "target_language" in options:
            options.setdefault("translation_profile", "language_target_v1")
        if role == "vocalize" and "batch_policy" not in options:
            options.update(
                batch_policy="streamed_vocalization_v2", max_model_calls="4096"
            )
            options.setdefault("strength", "conservative")
        if long_mode and role in {
            "extract_audio",
            "preprocess_audio",
            "generate_subtitle",
        }:
            options.setdefault("media_budget", "audio_long_v5")
            if role == "preprocess_audio":
                options.setdefault("processing_profile", "regions_long_v5")
                options.setdefault("vad_mode", "off")
                options.setdefault("audio_filter", "off")
            if role == "generate_subtitle":
                options.setdefault("format", "srt")
    return result
