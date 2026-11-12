import httpx
import pytest

from mideagent_model_tools.endpoints import EndpointFailure, OpenAITextAdapter


def test_adapter_response_capacity_keeps_v1_code_but_v2_does_not_advance():
    from video_service.role_policy import endpoint_error_code

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 262145)

    adapter = OpenAITextAdapter("http://127.0.0.1:9/v1", transport=httpx.MockTransport(respond), approved_origins={"http://127.0.0.1:9"})
    try:
        with pytest.raises(EndpointFailure) as caught:
            adapter.chat("fixture", [{"role": "user", "content": "hello"}])
    finally:
        adapter.close()
    assert caught.value.code == "invalid_response"
    assert endpoint_error_code(caught.value, v2=False) == "invalid_response"
    assert endpoint_error_code(caught.value, v2=True) == "output_capacity_exceeded"
    assert len(calls) == 1


def test_guarded_sdk_transport_marks_capacity_without_loading_or_calling_sdk():
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from video_service.role_policy import endpoint_error_code

    transport = _GuardedTransport(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 262145)),
        "http://127.0.0.1:9/v1", "/chat/completions", None, "fixture", {},
    )
    with httpx.Client(transport=transport, trust_env=False) as client:
        with pytest.raises(EndpointFailure) as caught:
            client.post("http://127.0.0.1:9/v1/chat/completions", json={"model": "fixture"})
    assert caught.value is transport.failure
    assert caught.value.code == "invalid_response"
    assert endpoint_error_code(caught.value, v2=True) == "output_capacity_exceeded"
    assert transport.calls == 1
