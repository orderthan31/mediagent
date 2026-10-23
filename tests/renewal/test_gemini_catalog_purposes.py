"""Pure capability regressions, independent of provider inference/authentication.

The Pro descriptor fields below reproduce the actual existing-key non-generative
catalog observation; they are not a new successful inference or a fixture account list.
"""

from video_service.model_catalog import classify


def test_live_gemini25pro_metadata_is_a_text_translation_candidate_not_timed_asr():
    raw = {
        "id": "gemini-2.5-pro",
        "name": "models/gemini-2.5-pro",
        "version": "2.5",
        "supportedGenerationMethods": [
            "generateContent",
            "countTokens",
            "createCachedContent",
            "batchGenerateContent",
        ],
    }
    row = classify("gemini", raw, "gemini")
    assert row["profile"] is not None
    assert row["runtime_uses"] == ["translation"]
    assert row["classification_status"] == "supported"
    assert "speech_recognition" not in row["profile"]["capabilities"]
    assert (
        "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro" in row["evidence"]
    )


def test_non_descriptor_alias_requires_catalog_version_witness_and_keeps_exact_id():
    import httpx
    from video_service.model_catalog import fetch_catalog

    def discovered(models):
        return fetch_catalog(
            "gemini",
            "synthetic-nonoperating-key",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"models": models})
            ),
        )

    canonical = {
        "name": "models/gemini-2.5-pro",
        "version": "2.5-pro",
        "supportedGenerationMethods": ["generateContent"],
    }
    alias = {
        "name": "models/gemini-pro-latest",
        "version": "2.5-pro",
        "supportedGenerationMethods": ["generateContent"],
    }
    rows = discovered([canonical, alias])
    found = {r["id"]: r for r in rows}
    assert found["gemini-pro-latest"]["runtime_uses"] == ["translation"]
    assert found["gemini-pro-latest"]["id"] == "gemini-pro-latest"
    assert "별칭" in found["gemini-pro-latest"]["reason"]
    assert discovered([alias])[0]["profile"] is None
    different = {**alias, "version": "unverified-future-variant"}
    assert (
        next(
            r
            for r in discovered([canonical, different])
            if r["id"] == "gemini-pro-latest"
        )["classification_status"]
        == "unknown"
    )


import pytest


@pytest.mark.parametrize(
    "model",
    [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-4-argon",
    ],
)
def test_verified_text_model_evidence_only_exposes_current_translation_candidate(model):
    row = classify(
        "gemini",
        {"id": model, "supportedGenerationMethods": ["generateContent"]},
        "gemini",
    )
    assert row["runtime_uses"] == ["translation"]
    assert row["classification_status"] == "supported"
    assert row["evidence"]
    assert row["inference_verified"] is False
    assert "speech_recognition" not in row["profile"]["capabilities"]


@pytest.mark.parametrize(
    "alias,base,version",
    [
        ("gemini-flash-latest", "gemini-3.8-flash", "3.8-flash-09-2026"),
        ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "3.5-flash-lite-07-2026"),
    ],
)
def test_controlled_latest_variations_use_verified_same_response_versions(
    alias, base, version
):
    import httpx
    from video_service.model_catalog import fetch_catalog

    rows = [
        {
            "name": "models/" + base,
            "version": version,
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/" + alias,
            "version": version,
            "supportedGenerationMethods": ["generateContent"],
        },
    ]
    result = fetch_catalog(
        "gemini",
        "synthetic-key-only",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": rows})
        ),
    )
    found = next(row for row in result if row["id"] == alias)
    assert found["runtime_uses"] == ["translation"]
    assert found["classification_status"] == "supported"
    assert found["id"] == alias
    assert "별칭" in found["reason"]


@pytest.mark.parametrize(
    "model,methods,purpose",
    [
        ("gemini-2.5-flash-image", ["generateContent"], "이미지"),
        ("gemini-3.8-flash-tts", ["generateContent"], "음성 생성"),
        ("gemini-3.5-transcribe", ["generateContent"], "전사"),
        ("gemini-embedding-001", ["embedContent"], "임베딩"),
        ("gemini-3.8-live", ["bidiGenerateContent"], "스트리밍"),
        ("gemini-3.1-flash-lite-preview", ["generateContent"], "종료"),
    ],
)
def test_known_nonconnector_models_are_unsupported_not_unknown_or_timed_asr(
    model, methods, purpose
):
    row = classify(
        "gemini", {"id": model, "supportedGenerationMethods": methods}, "gemini"
    )
    assert row["classification_status"] == "unsupported"
    assert row["profile"] is None and row["runtime_uses"] == []
    assert purpose in row["provider_purpose"]
    assert row["evidence"]


def test_unverified_prefix_does_not_manufacture_purpose_from_generatecontent():
    row = classify(
        "gemini",
        {
            "id": "gemini-unverified-future-pro",
            "supportedGenerationMethods": ["generateContent"],
        },
        "gemini",
    )
    assert row["classification_status"] == "unknown"
    assert row["profile"] is None and row["runtime_uses"] == []


def test_gemini_purpose_never_crosses_wrong_wire_protocol():
    row = classify(
        "gemini",
        {"id": "gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
        "openai",
    )
    assert row["profile"] is None
    assert row["runtime_uses"] == []
    assert row["classification_status"] == "unsupported"


def test_existing_three_profiles_remain_exactly_the_prior_canonical_contract():
    from video_service.model_profile import validate_profile

    prior = validate_profile(
        model_types=["text", "vision", "multimodal"],
        input_modalities=["audio", "image", "text", "video"],
        output_modalities=["text"],
        capabilities=["image_understanding", "text_generation"],
    )
    for name in ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]:
        row = classify(
            "gemini",
            {"id": name, "supportedGenerationMethods": ["generateContent"]},
            "gemini",
        )
        assert row["profile"] == prior
        assert row["runtime_uses"] == ["translation"]


@pytest.mark.parametrize(
    "model,target",
    [
        ("gemini-3.5-flash", "gemini-3.6-flash"),
        ("gemini-3.7-flash", "gemini-3.8-flash"),
    ],
)
def test_documented_provider_routing_is_disclosed_without_rewriting_selected_id(
    model, target
):
    row = classify(
        "gemini",
        {"id": model, "supportedGenerationMethods": ["generateContent"]},
        "gemini",
    )
    assert row["id"] == model
    assert target in row["reason"] and "제공사" in row["reason"]


@pytest.mark.parametrize(
    "model,title,description",
    [
        (
            "gemini-flash-latest",
            "Gemini Flash Latest",
            "Latest release of Gemini Flash",
        ),
        (
            "gemini-flash-lite-latest",
            "Gemini Flash-Lite Latest",
            "Latest release of Gemini Flash-Lite",
        ),
        ("gemini-pro-latest", "Gemini Pro Latest", "Latest release of Gemini Pro"),
    ],
)
def test_actual_alias_human_version_is_not_invented_into_an_underlying_model(
    model, title, description
):
    # Exact observed descriptor; actual version is a human label, not a canonical ID.
    row = classify(
        "gemini",
        {
            "id": model,
            "name": "models/" + model,
            "version": title,
            "displayName": title,
            "description": description,
            "supportedGenerationMethods": ["generateContent"],
        },
        "gemini",
    )
    assert row["runtime_uses"] == ["translation"]
    assert row["id"] == model
    assert "미고정" in row["reason"]
    assert "python-genai" in " ".join(row["evidence"])
