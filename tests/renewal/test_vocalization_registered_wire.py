"""Controlled wire contracts, not recognition quality or operating provider use."""

import base64
import hashlib
import json

import httpx
import pytest
from test_vocalization_proposals import pcm
from video_service.model_profile import supports_vocalization
from video_service.vocalization_endpoints import GeminiVocalizationAdapter
from video_service.vocalization_proposals import CONFIRM_SCHEMA, EVENT_SCHEMA, POLICY


def context(clips, phase="detect"):
    return {
        "purpose": "vocalization_regions_v1",
        "phase": phase,
        "binding_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "source_frames": 16000,
        "source_language": "en",
        "max_calls": 2,
        "call_index": 0,
        "clips": [
            {
                "start_frame": 0,
                "end_frame": 16000,
                "sha256": hashlib.sha256(clip).hexdigest(),
            }
            for clip in clips
        ],
        "instruction": POLICY + " Preserve uncertain sounds.",
    }


def test_vocalization_requires_explicit_audio_decision_capability():
    profile = {
        "model_types": ["decision", "multimodal"],
        "input_modalities": ["audio", "text"],
        "output_modalities": ["text"],
        "capabilities": ["structured_output"],
    }
    assert not supports_vocalization(profile, "gemini", "gemini-2.5-flash")
    profile["capabilities"].append("vocalization_classification")
    assert supports_vocalization(profile, "gemini", "gemini-2.5-flash")
    assert not supports_vocalization(profile, "openai", "gemini-2.5-flash")


def test_detect_and_confirmation_use_actual_audio_and_exact_structured_schema():
    requests = []
    clip = pcm(1)

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        parts = body["contents"][0]["parts"]
        assert base64.b64decode(parts[0]["inlineData"]["data"]) == clip
        schema = body["generationConfig"]["responseSchema"]
        result = (
            []
            if schema == EVENT_SCHEMA
            else {"kind": "uncertain", "safe_to_remove": False, "speech_overlap": True}
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(result)}]},
                    }
                ]
            },
        )

    adapter = GeminiVocalizationAdapter(
        "http://127.0.0.1:9978/v1",
        transport=httpx.MockTransport(respond),
        approved_origins={"http://127.0.0.1:9978"},
        api_key=None,
    )
    try:
        assert (
            adapter.classify("gemini-2.5-flash", context([clip]), [clip], EVENT_SCHEMA)
            == []
        )
        result = adapter.classify(
            "gemini-2.5-flash",
            context([clip, clip], "confirm"),
            [clip, clip],
            CONFIRM_SCHEMA,
        )
        assert result["speech_overlap"] and not result["safe_to_remove"]
        assert len(requests) == 2
    finally:
        adapter.close()


@pytest.mark.parametrize("change", ["clip", "purpose", "phase", "budget"])
def test_changed_clip_purpose_phase_or_budget_never_enters_transport(change):
    clip = pcm(1)
    value = context([clip])
    calls = []
    if change == "clip":
        value["clips"][0]["sha256"] = "0" * 64
    elif change == "purpose":
        value["purpose"] = "translation"
    elif change == "phase":
        value["phase"] = "confirm"
    else:
        value["call_index"] = 2
    adapter = GeminiVocalizationAdapter(
        "http://127.0.0.1:9978/v1",
        transport=httpx.MockTransport(lambda r: calls.append(r)),
        approved_origins={"http://127.0.0.1:9978"},
        api_key=None,
    )
    try:
        with pytest.raises(ValueError):
            adapter.classify("gemini-2.5-flash", value, [clip], EVENT_SCHEMA)
        assert calls == []
    finally:
        adapter.close()


def test_invalid_model_reply_never_becomes_an_accepted_vocal_event():
    from video_service.model_endpoints import EndpointFailure

    requests = []
    clip = pcm(1)

    def reply(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"start":0,"end":1,"kind":"grunt","certain":"true"}]'
                                }
                            ]
                        },
                    }
                ]
            },
        )

    adapter = GeminiVocalizationAdapter(
        "http://127.0.0.1:9978/v1",
        transport=httpx.MockTransport(reply),
        approved_origins={"http://127.0.0.1:9978"},
        api_key=None,
    )
    try:
        with pytest.raises(EndpointFailure):
            adapter.classify("gemini-2.5-flash", context([clip]), [clip], EVENT_SCHEMA)
        assert len(requests) == 1
    finally:
        adapter.close()
