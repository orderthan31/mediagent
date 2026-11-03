"""Cost-free model-selection contracts; no database, jobs or outbound sockets."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for project in ["packages/shared", "tools/models", "tools/media", "agents", "apps/orchestrator", "packages/tool-hub", "runtime/controlnet"]:
    sys.path.insert(0, str(ROOT / project))

import pytest
from video_service.model_profile import supports_transcription


@pytest.mark.parametrize("protocol", ["gemini", "openai", "openai_compatible"])
def test_timed_asr_eligibility_is_not_a_model_name_allowlist(protocol):
    profile = {
        "model_types": ["multimodal"],
        "input_modalities": ["audio", "text"],
        "output_modalities": ["text"],
        "capabilities": ["speech_recognition", "structured_output", "text_generation"],
    }
    assert supports_transcription(profile, protocol, "workflow-selected-voice-model-r9")


def test_workflow_llm_options_survive_compile_without_changing_model_references():
    import json
    from mideagent_orchestrator.workflow import default_definition, compile_definition, validate
    graph = default_definition()
    for index, node in enumerate(graph["nodes"][:2]):
        node["model_ref"] = {"model_id": str(index + 1) * 32, "revision": 7 + index}
        node["options"]["llm_options"] = json.dumps({"temperature": 0.2 + index / 10, "max_tokens": 1024})
    assert validate(graph)["valid"], "Workflow must accept bounded model options, not hardcoded SDK settings"
    native = compile_definition(graph)["definition"]
    for public in graph["nodes"][:2]:
        node = next(n for n in native["nodes"] if n.get("model_ref") == public["model_ref"])
        assert node["options"]["llm_options"] == public["options"]["llm_options"]


def test_actual_sdk_adapter_is_present_in_the_model_tool_package():
    import importlib.util
    assert importlib.util.find_spec("mideagent_model_tools.litellm_adapter") is not None, "Actual SDK adapter is not implemented"


def test_workflow_options_cannot_override_credentials_model_transport_or_retries():
    import importlib.util
    assert importlib.util.find_spec("video_service.llm_contract") is not None, "Frozen invocation contract missing"
    from video_service.llm_contract import parse_options
    for key in ["api_key", "model", "api_base", "client", "num_retries", "fallbacks", "headers"]:
        with pytest.raises(ValueError):
            parse_options('{"' + key + '":"forbidden"}')


@pytest.mark.parametrize("option", ["max_tokens", "top_p", "seed", "reasoning_effort"])
def test_native_transcription_options_are_rejected_not_silently_discarded(option):
    import json
    from video_service.llm_contract import freeze_inference
    row = {"protocol": "openai", "provider": "openai", "remote_model": "workflow-selected-model", "model_id": "a" * 32, "revision": 7,
           "model_types": ["speech_recognition"], "input_modalities": ["audio"], "output_modalities": ["text"], "capabilities": ["speech_recognition"]}
    value = "low" if option == "reasoning_effort" else 1
    with pytest.raises(ValueError):
        freeze_inference(row, "transcription", json.dumps({option: value}))


def test_frozen_binding_keeps_exact_model_revision_and_workflow_options():
    import importlib.util
    assert importlib.util.find_spec("video_service.llm_contract") is not None, "Frozen invocation contract missing"
    from video_service.llm_contract import freeze_inference
    row = {"protocol": "gemini", "provider": "gemini", "remote_model": "arbitrary-selected-llm", "model_id": "a" * 32, "revision": 7,
           "model_types": ["multimodal"], "input_modalities": ["audio", "text"], "output_modalities": ["text"],
           "capabilities": ["speech_recognition", "text_generation", "structured_output"]}
    contract = freeze_inference(row, "transcription", '{"max_tokens":2048,"timeout":60}')
    assert contract["operation"] == "structured_audio"
    assert contract["options"] == {"max_tokens": 2048, "timeout": 60}
    assert contract["model"] == row["remote_model"]
    assert contract["revision"] == row["revision"]


def test_new_binding_freezes_sdk_but_legacy_binding_is_not_rewritten():
    import inspect, json
    from video_service.postgres.intake import Intake
    assert "sdk" in inspect.signature(Intake._bindings).parameters, "Only new creation must freeze an SDK invocation contract"
    row = {"model_id": "a" * 32, "revision": 7, "remote_model": "chosen-by-workflow", "connection_id": "c" * 32,
           "connection_revision": 2, "sha256": "d" * 64, "endpoint": "https://unit.invalid/v1", "protocol": "openai", "provider": "openai", "credential_ref": "db:" + "e" * 32,
           "model_types": ["text"], "input_modalities": ["text"], "output_modalities": ["text"], "capabilities": ["text_generation"], "model_active": True, "connection_active": True}
    class DB:
        def execute(self, sql, params):
            assert params[1:] == (row["model_id"], 7)
            return self
        def fetchone(self):
            return row.copy()
    definition = {"nodes": [{"id": "translate", "type": "translate", "model_ref": {"model_id": row["model_id"], "revision": 7}, "options": {"llm_options": '{"temperature":0.7,"max_tokens":512}'}}]}
    intake = object.__new__(Intake)
    old = intake._bindings(DB(), "b" * 32, definition)
    fresh = intake._bindings(DB(), "b" * 32, definition, sdk=True)
    assert "inference" not in old["translate"]
    frozen = fresh["translate"]["inference"]
    assert frozen["model"] == row["remote_model"] and frozen["revision"] == 7
    assert frozen["options"] == {"temperature": 0.7, "max_tokens": 512}
    for key, value in old["translate"].items():
        assert fresh["translate"][key] == value


def test_actual_creation_handler_explicitly_freezes_new_sdk_bindings():
    import ast, inspect, textwrap
    from mideagent_orchestrator.execution import Execution
    tree = ast.parse(textwrap.dedent(inspect.getsource(Execution.create)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_bindings"]
    assert calls and all(any(k.arg == "sdk" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords) for call in calls), "New jobs must freeze SDK settings in the actual create method"



def test_catalog_uses_sdk_capabilities_not_an_application_model_allowlist(monkeypatch):
    from video_service import model_catalog
    assert hasattr(model_catalog, "sdk_profile"), "Catalog still relies on hardcoded LLM names"
    monkeypatch.setattr(model_catalog, "sdk_profile", lambda provider, model: {
        "profile": {"model_types": ["text"], "input_modalities": ["text"], "output_modalities": ["text"], "capabilities": ["text_generation", "structured_output"]},
        "evidence": ["https://github.com/BerriAI/litellm"], "profile_variants": {}})
    row = model_catalog.classify("openai", {"id": "new-workflow-selected-llm-not-in-any-list"}, "openai")
    assert row["id"] == "new-workflow-selected-llm-not-in-any-list"
    assert row["profile"]["capabilities"] == ["structured_output", "text_generation"]
    assert row["runtime_uses"] == ["translation"]


@pytest.fixture(autouse=True)
def no_provider_sockets(monkeypatch):
    import socket
    connect = socket.socket.connect
    def deny_external(sock, address):
        # Windows asyncio creates a loopback self-pipe; it is not a model client.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        raise AssertionError("External network is forbidden in these cost-free tests")
    monkeypatch.setattr(socket.socket, "connect", deny_external)


@pytest.mark.parametrize("protocol,model", [("openai", "new-nonlegacy-voice-model"), ("gemini", "unprefixed-workflow-voice")])
def test_historical_asr_rejection_stays_unchanged_while_new_sdk_selection_is_allowed(protocol, model):
    from types import SimpleNamespace
    from video_service.postgres.transcription import TranscriptionRuntime
    from video_service.llm_contract import freeze_inference
    row = {"owner_id": "a" * 32, "model_id": "b" * 32, "revision": 9, "sha256": "e" * 64,
           "connection_id": "c" * 32, "connection_revision": 2, "credential_ref": "db:" + "d" * 32,
           "remote_model": model, "protocol": protocol, "provider": protocol, "endpoint": "https://unit.invalid/v1",
           "model_types": ["multimodal"], "input_modalities": ["audio", "text"], "output_modalities": ["text"],
           "capabilities": ["speech_recognition", "text_generation", "structured_output"]}
    credentials = SimpleNamespace(model=lambda *args: row.copy(), resolve=lambda *args: "unit-key")
    runtime = TranscriptionRuntime(credentials, transport_factory=lambda: None, approved_origins={"https://unit.invalid"}, mode="external")
    assert not runtime.available(row), "Historical unsupported pins must not become executable after SDK rollout"
    fresh = {**row, "inference": freeze_inference(row, "transcription")}
    assert runtime.available(fresh), "New workflow SDK eligibility must not use a legacy model-name gate"


def test_recovery_creation_preserves_parent_invocation_contract_without_retargeting():
    from copy import deepcopy
    from mideagent_orchestrator.execution import Execution
    assert hasattr(Execution, "_creation_model_bindings"), "Recovery must preserve original model invocation semantics"
    definition, options = {"nodes": []}, {"source_language": "auto"}
    old = {"transcribe": {"model_id": "a" * 32, "revision": 7}}
    parent = {"snapshot": {"definition": deepcopy(definition), "options": deepcopy(options), "model_bindings": deepcopy(old)}}
    fresh = {"transcribe": {**old["transcribe"], "inference": {"adapter": "litellm"}}}
    assert Execution._creation_model_bindings(parent, definition, options, fresh) == old
    assert Execution._creation_model_bindings(None, definition, options, fresh) == fresh
    changed = {**options, "target_language": "ko"}
    assert Execution._creation_model_bindings(parent, definition, changed, fresh) == fresh
    assert parent["snapshot"]["model_bindings"] == old


def test_runtime_factories_use_the_sdk_only_for_new_frozen_contracts():
    import httpx
    from types import SimpleNamespace
    from video_service.llm_contract import freeze_inference
    from video_service.postgres.translation import TranslationRuntime
    from video_service.postgres.transcription import TranscriptionRuntime
    from mideagent_model_tools.litellm_adapter import LiteLLMAdapter
    for runtime_type, role in [(TranslationRuntime, "translation"), (TranscriptionRuntime, "transcription")]:
        pin = {"owner_id": "a" * 32, "model_id": "b" * 32, "revision": 9, "remote_model": "selected-at-revision-nine", "protocol": "gemini", "provider": "gemini",
               "endpoint": "https://unit.invalid/v1beta", "model_types": ["multimodal"], "input_modalities": ["audio", "text"], "output_modalities": ["text"],
               "capabilities": ["speech_recognition", "text_generation", "structured_output"]}
        pin["inference"] = freeze_inference(pin, role, '{"timeout":77}')
        runtime = runtime_type(SimpleNamespace(), transport_factory=lambda: httpx.MockTransport(lambda r: None), approved_origins={"https://unit.invalid"}, mode="external")
        adapter = runtime.make_adapter(pin, "unit-credential")
        try:
            assert isinstance(adapter, LiteLLMAdapter), "Actual role factory still bypasses the SDK"
            assert adapter._client.timeout.read == 77
        finally:
            adapter.close()
        old = runtime.make_adapter({k: v for k, v in pin.items() if k != "inference"}, "unit-credential")
        try:
            assert not isinstance(old, LiteLLMAdapter), "Historical pinned requests must not be silently reinterpreted"
        finally:
            old.close()


def sdk_adapter(protocol, operation, wire, model="workflow-selected-model", key="unit-credential-one", options=None):
    import importlib.util
    assert importlib.util.find_spec("mideagent_model_tools.litellm_adapter") is not None, "SDK adapter missing"
    import httpx
    from mideagent_model_tools.litellm_adapter import LiteLLMAdapter
    contract = {"version": 1, "adapter": "litellm", "provider": "openai" if protocol == "openai_compatible" else protocol,
                "model": model, "model_id": "a" * 32, "revision": 7, "role": "translation" if operation == "translation" else "transcription",
                "operation": operation, "options": options or {}}
    return LiteLLMAdapter("https://unit.invalid" + ("/v1beta" if protocol == "gemini" else "/v1" if protocol != "anthropic" else ""),
                          protocol=protocol, contract=contract, transport=httpx.MockTransport(wire), approved_origins={"https://unit.invalid"}, api_key=key)


def reply(protocol, model, text):
    if protocol == "gemini":
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}}
    if protocol == "anthropic":
        return {"id": "msg_unit", "type": "message", "role": "assistant", "model": model, "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
    return {"id": "unit", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


@pytest.mark.parametrize("protocol", ["openai", "gemini", "anthropic"])
def test_actual_sdk_preserves_selected_llm_options_and_request_credentials(protocol, monkeypatch):
    import httpx, json, socket
    original = socket.socket.connect
    def deny_external(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original(sock, address)
        raise AssertionError("No external sockets allowed")
    monkeypatch.setattr(socket.socket, "connect", deny_external)
    seen = []
    model = "gemini-3.8-flash" if protocol == "gemini" else "workflow-chosen-different-model"
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json=reply(protocol, model, '{"translations":["한국어"]}'))
    adapter = sdk_adapter(protocol, "translation", wire, model=model, options={**({"temperature": 0.2} if protocol != "gemini" else {}), "max_tokens": 1024, "timeout": 60})
    try:
        assert json.loads(adapter.chat(model, [{"role": "system", "content": "Translate to Korean"}, {"role": "user", "content": '["hello"]'}])) == ["한국어"]
    finally:
        adapter.close()
    assert len(seen) == 1
    body = json.loads(seen[0].content)
    if protocol == "gemini":
        assert "/models/" + model + ":generateContent" in seen[0].url.path
        assert body["generationConfig"]["max_output_tokens"] == 1024
        assert "response_json_schema" in body["generationConfig"]
    else:
        assert body["model"] == model
        assert body["temperature"] == 0.2
    assert seen[0].url.host == "unit.invalid"
    assert any(value in ("unit-credential-one", "Bearer unit-credential-one") for name, value in seen[0].headers.items() if name in ("authorization", "x-api-key", "x-goog-api-key"))


def test_sdk_cannot_silently_replace_structured_response_schema_with_a_prompt():
    import httpx
    from video_service.model_endpoints import EndpointFailure
    seen = []
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json=reply("gemini", "unknown-schema-capability", '{"translations":["ok"]}'))
    adapter = sdk_adapter("gemini", "translation", wire, model="unknown-schema-capability")
    try:
        with pytest.raises(EndpointFailure):
            adapter.chat("unknown-schema-capability", [{"role": "user", "content": "hello"}])
    finally:
        adapter.close()
    assert not seen, "SDK schema downgrade must be rejected before external bytes"


@pytest.mark.parametrize("protocol,thinking", [
    ("openai", {"reasoning_effort": "low"}),
    ("openai", {"thinking": None}),
    ("openai", {"output_config": {"format": {"type": "json_schema"}}}),
    ("gemini", {"thinking_config": None}),
    ("gemini", {"thinking_config": {"thinking_level": "low"}}),
    ("gemini", {"thinking_config": {"thinking_budget": 0}}),
    ("gemini", {"thinking_config": {"thinking_level": "high"}, "thinkingConfig": {"thinkingLevel": "low"}}),
    ("anthropic", {"output_config": {"effort": "low"}}),
    ("anthropic", {"thinking": {"type": "disabled"}, "output_config": {"effort": "high"}}),
])
def test_changed_missing_or_disabled_reasoning_never_reaches_delegate(protocol, thinking):
    import httpx
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from video_service.model_endpoints import EndpointFailure
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    config = {"response_json_schema": schema, **thinking} if protocol == "gemini" else thinking
    body = {"generationConfig": config} if protocol == "gemini" else {"model": "fixture", "response_format": {"json_schema": {"schema": schema}}, **config}
    seen = []
    path = "/models/fixture:generateContent" if protocol == "gemini" else "/v1/messages" if protocol == "anthropic" else "/chat/completions"
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json={"answer": "fixture"})
    guard = _GuardedTransport(httpx.MockTransport(wire), "https://unit.invalid", path, None, "fixture", {"reasoning_effort": "high"})
    guard.schema = schema
    try:
        with pytest.raises(EndpointFailure):
            guard.handle_request(httpx.Request("POST", "https://unit.invalid" + path, json=body))
    finally:
        guard.close()
    assert not seen


@pytest.mark.parametrize("protocol,thinking", [
    ("openai", {"reasoning_effort": "high"}),
    ("gemini", {"thinking_config": {"thinking_level": "HIGH"}}),
    ("anthropic", {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}),
])
def test_exact_supported_reasoning_level_is_preserved(protocol, thinking):
    import httpx
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    body = {"generationConfig": {"response_json_schema": schema, **thinking}} if protocol == "gemini" else {"model": "fixture", "response_format": {"json_schema": {"schema": schema}}, **thinking}
    seen = []
    path = "/models/fixture:generateContent" if protocol == "gemini" else "/v1/messages" if protocol == "anthropic" else "/chat/completions"
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json={"answer": "fixture"})
    guard = _GuardedTransport(httpx.MockTransport(wire), "https://unit.invalid", path, None, "fixture", {"reasoning_effort": "high"})
    guard.schema = schema
    try:
        response = guard.handle_request(httpx.Request("POST", "https://unit.invalid" + path, json=body))
        response.close()
    finally:
        guard.close()
    assert len(seen) == 1


@pytest.mark.parametrize("sent_temperature", [None, "0.1"])
def test_native_temperature_cannot_be_missing_or_changed(sent_temperature):
    import httpx
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from video_service.model_endpoints import EndpointFailure
    seen = []
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json={"segments": []})
    fields = {"model": "fixture"}
    if sent_temperature is not None:
        fields["temperature"] = sent_temperature
    guard = _GuardedTransport(httpx.MockTransport(wire), "https://unit.invalid", "/audio/transcriptions", None, "fixture", {"temperature": 0.2})
    try:
        request = httpx.Request("POST", "https://unit.invalid/audio/transcriptions", data=fields, files={"file": ("audio.wav", b"unit-audio-fixture")})
        with pytest.raises(EndpointFailure):
            guard.handle_request(request)
    finally:
        guard.close()
    assert not seen


def test_sdk_cannot_retry_an_openai_role_repair_or_upstream_failure():
    import httpx
    from video_service.model_endpoints import EndpointFailure
    seen = []
    def wire(request):
        seen.append(request)
        return httpx.Response(400, json={"error": {"message": "unsupported role system; replace with user", "type": "invalid_request_error"}})
    adapter = sdk_adapter("openai", "translation", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.chat("workflow-selected-model", [{"role": "user", "content": "hi"}])
    finally:
        adapter.close()
    assert len(seen) == 1


@pytest.mark.parametrize("field", ["pre_call_rules", "post_call_rules", "headers", "set_verbose"])
def test_sdk_global_executable_or_account_state_is_rejected_before_sdk_call(field, monkeypatch, caplog):
    import litellm, httpx
    from video_service.model_endpoints import EndpointFailure
    observed, seen = [], []
    if field == "headers":
        value = {"x-other-account-tenant": "must-never-cross-account"}
    elif field == "set_verbose":
        value = True
    else:
        value = [lambda text: observed.append(text) or True]
    monkeypatch.setattr(litellm, field, value)
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json=reply("openai", "workflow-selected-model", '{"translations":["PRIVATE_RESPONSE_MARKER"]}'))
    adapter = sdk_adapter("openai", "translation", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.chat("workflow-selected-model", [{"role": "user", "content": "PRIVATE_PROMPT_MARKER"}])
    finally:
        adapter.close()
    assert not seen and not observed
    assert "PRIVATE_PROMPT_MARKER" not in caplog.text
    assert "PRIVATE_RESPONSE_MARKER" not in caplog.text


def test_sdk_debug_logger_cannot_emit_payloads(monkeypatch, caplog):
    import logging, httpx
    from video_service.model_endpoints import EndpointFailure
    caplog.set_level(logging.DEBUG, logger="LiteLLM")
    seen = []
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json=reply("openai", "workflow-selected-model", '{"translations":["PRIVATE_RESPONSE_MARKER"]}'))
    adapter = sdk_adapter("openai", "translation", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.chat("workflow-selected-model", [{"role": "user", "content": "PRIVATE_PROMPT_MARKER"}])
    finally:
        adapter.close()
    assert not seen
    assert "PRIVATE_PROMPT_MARKER" not in caplog.text
    assert "PRIVATE_RESPONSE_MARKER" not in caplog.text


def test_sdk_global_model_alias_cannot_replace_the_selected_llm(monkeypatch):
    import litellm, httpx
    from video_service.model_endpoints import EndpointFailure
    monkeypatch.setattr(litellm, "model_alias_map", {"workflow-selected-model": "not-the-selected-model"})
    seen = []
    def wire(request):
        seen.append(request)
        return httpx.Response(200, json=reply("openai", "not-the-selected-model", '{"translations":["ok"]}'))
    adapter = sdk_adapter("openai", "translation", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.chat("workflow-selected-model", [{"role": "user", "content": "hello"}])
    finally:
        adapter.close()
    assert seen == []


@pytest.mark.parametrize("protocol", ["openai", "gemini"])
def test_sdk_user_keys_are_request_scoped_and_responses_are_not_reused(protocol):
    import httpx, json, litellm
    seen = []
    model = "gemini-3.8-flash" if protocol == "gemini" else "workflow-selected-model"
    def wire(request):
        seen.append(request.headers.get("x-goog-api-key") if protocol == "gemini" else request.headers.get("authorization"))
        return httpx.Response(200, json=reply(protocol, model, '{"translations":["ok"]}'))
    for key in ["unit-account-one", "unit-account-two"]:
        adapter = sdk_adapter(protocol, "translation", wire, key=key, model=model)
        try:
            assert json.loads(adapter.chat(model, [{"role": "user", "content": "same input"}])) == ["ok"]
        finally:
            adapter.close()
    prefix = "" if protocol == "gemini" else "Bearer "
    assert seen == [prefix + "unit-account-one", prefix + "unit-account-two"]
    assert litellm.api_key is None
    assert litellm.client_session is None


def test_sdk_preserves_actual_http_status_and_redacts_key_from_detail():
    import httpx
    from video_service.model_endpoints import EndpointFailure
    adapter = sdk_adapter("openai", "translation", lambda r: httpx.Response(403, json={"error": "denied unit-credential-one"}))
    try:
        with pytest.raises(EndpointFailure) as caught:
            adapter.chat("workflow-selected-model", [{"role": "user", "content": "hello"}])
    finally:
        adapter.close()
    assert caught.value.http_status == 403
    assert caught.value.code == "authentication_failed"
    assert "unit-credential-one" not in caught.value.upstream_detail


@pytest.mark.parametrize("protocol,operation", [("gemini", "structured_audio"), ("openai", "structured_audio"), ("openai", "audio_transcription")])
def test_actual_sdk_audio_contains_selected_model_and_returns_only_real_times(protocol, operation):
    import httpx, io, wave, json
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\x00\x00" * 1600)
    seen = []
    model = "gemini-3.8-flash" if protocol == "gemini" else "workflow-selected-model"
    def wire(request):
        seen.append(request)
        segment = {"start": 0, "end": 0.08, "text": "fixture speech"}
        data = {"text": "fixture speech", "segments": [segment]} if operation == "audio_transcription" else reply(protocol, model, json.dumps({"segments": [segment]}))
        return httpx.Response(200, json=data)
    adapter = sdk_adapter(protocol, operation, wire, model=model)
    try:
        assert adapter.transcribe(model, stream.getvalue(), "en") == [{"start": 0, "end": 0.08, "text": "fixture speech"}]
    finally:
        adapter.close()
    assert len(seen) == 1
    if operation == "structured_audio":
        body = json.loads(seen[0].content)
        assert "audio" in seen[0].content.decode().lower()
        assert model in (seen[0].url.path if protocol == "gemini" else body["model"])
    else:
        assert b"workflow-selected-model" in seen[0].content
        assert b"verbose_json" in seen[0].content


def test_native_word_output_with_missing_interior_times_is_rejected():
    import httpx, io, wave
    from video_service.model_endpoints import EndpointFailure
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\x00\x00" * 1600)
    def wire(request):
        return httpx.Response(200, json={"text": "a b c", "words": [{"word": "a", "start": 0, "end": 0.02}, {"word": "b"}, {"word": "c", "start": 0.06, "end": 0.08}]})
    adapter = sdk_adapter("openai", "audio_transcription", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.transcribe("workflow-selected-model", stream.getvalue(), "en")
    finally:
        adapter.close()


@pytest.mark.parametrize("segments", [[{"end": 0.08, "text": "missing start"}], [{"start": 0, "end": 9, "text": "outside audio"}], [{"start": 0, "end": 0.08, "text": "too many"}] * 101])
def test_malformed_upstream_timing_is_a_normal_invalid_response_failure(segments):
    import httpx, io, wave
    from video_service.model_endpoints import EndpointFailure
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\x00\x00" * 1600)
    adapter = sdk_adapter("openai", "audio_transcription", lambda request: httpx.Response(200, json={"text": "fixture", "segments": segments}))
    try:
        with pytest.raises(EndpointFailure) as caught:
            adapter.transcribe("workflow-selected-model", stream.getvalue(), "en")
        assert caught.value.code == "invalid_response"
    finally:
        adapter.close()


@pytest.mark.parametrize("configured,expected", [(None, 15), (77, 77)])
def test_production_pinned_socket_honors_new_timeout_and_preserves_legacy_default(configured, expected, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from video_service import registered_transport as module
    seen = []
    class Reply:
        status = 200
        def getheader(self, name, default=None): return default
        def getheaders(self): return [("content-type", "application/json")]
        def read(self, limit): return b"{}"
    class Connection:
        def __init__(self, host, port, timeout): seen.append(("http", timeout))
        def request(self, *args): pass
        def getresponse(self): return Reply()
        def close(self): pass
    def connect(address, timeout):
        seen.append(("socket", timeout))
        return SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(module.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(module.socket, "create_connection", connect)
    policy = SimpleNamespace(targets=((('http', 'unit.invalid', 80), ('127.0.0.1',)),))
    request = httpx.Request("POST", "http://unit.invalid/model", json={})
    if configured is not None:
        request.extensions["mideagent_timeout_seconds"] = configured
    response = module.PinnedModelTransport(policy).handle_request(request)
    assert response.status_code == 200
    assert seen == [("http", expected), ("socket", expected)]


def test_sdk_audio_without_real_timestamps_is_not_subtitle_input():
    import httpx, io, wave
    from video_service.model_endpoints import EndpointFailure
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\x00\x00" * 1600)
    def wire(request):
        return httpx.Response(200, json={"text": "words without timestamps"})
    adapter = sdk_adapter("openai", "audio_transcription", wire)
    try:
        with pytest.raises(EndpointFailure):
            adapter.transcribe("workflow-selected-model", stream.getvalue(), "en")
    finally:
        adapter.close()
