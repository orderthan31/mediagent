"""Gemini timed-audio registration variants; no provider calls or source mutation."""

import pytest
from video_service.model_catalog import classify
from video_service.model_profile import supports_transcription


@pytest.mark.parametrize(
    "model", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.8-flash"]
)
def test_verified_gemini_audio_has_explicit_transcription_profile_without_rewriting_translation_default(
    model,
):
    row = classify(
        "gemini",
        {"id": model, "supportedGenerationMethods": ["generateContent"]},
        "gemini",
    )
    assert row["runtime_uses"] == ["translation"]
    assert "speech_recognition" not in row["profile"]["capabilities"]
    variant = row.get("profile_variants", {}).get("transcription")
    assert variant is not None
    assert supports_transcription(variant["profile"], "gemini", row["id"])
    assert variant["runtime_uses"] == ["transcription", "translation"]
    assert any("/audio" in source for source in variant["evidence"])
    assert "실제" in variant["reason"] and "미검증" in variant["reason"]
