"""Real SDK serialization regression for the observed Gemini audio HTTP 400.

All HTTP responses here are explicit offline fixtures, not provider inference.
The separately retained live A/B receipts establish the actual provider behavior.
"""
import json
from copy import deepcopy

import httpx
import pytest

from mideagent_model_tools.endpoints import EndpointFailure
from mideagent_model_tools.litellm_adapter import LiteLLMAdapter
from test_audio_batches import wav
from test_litellm_model_tools import reply
from video_service.llm_contract import freeze_inference


def selected_model():
    return {
        'model_id': 'a' * 32, 'revision': 2, 'remote_model': 'gemini-3.8-flash',
        'protocol': 'gemini', 'provider': 'gemini',
        'model_types': ['multimodal'], 'input_modalities': ['audio', 'text'],
        'output_modalities': ['text'],
        'capabilities': ['speech_recognition', 'structured_output', 'text_generation'],
    }


@pytest.mark.parametrize('too_many', [False, True])
def test_actual_sdk_sends_portable_audio_schema_and_retains_local_result_bounds(too_many):
    row = selected_model()
    contract = freeze_inference(row, 'transcription', '{"max_tokens":4096,"timeout":30}')
    before = deepcopy(contract)
    calls = []

    def offline(request):
        body = json.loads(request.read())
        config = body['generationConfig']
        schema = config.get('response_json_schema', config.get('response_schema'))
        calls.append(body)
        assert schema['required'] == ['segments']
        assert 'additionalProperties' not in schema
        assert 'maxItems' not in schema['properties']['segments']
        item = schema['properties']['segments']['items']
        assert item['required'] == ['start', 'end', 'text']
        assert item['properties']['start']['type'].lower() == 'number'
        assert 'additionalProperties' not in item
        # Explicit offline response; too many rows must fail locally even when
        # the provider's portable wire schema omits an array-count keyword.
        rows = [{'start': 0, 'end': 1, 'text': 'offline fixture'}] * (101 if too_many else 1)
        return httpx.Response(200, json=reply('gemini', row['remote_model'],
            json.dumps({'segments': rows})))

    adapter = LiteLLMAdapter('https://sdk.unit.invalid/v1beta', protocol='gemini',
        contract=contract, transport=httpx.MockTransport(offline),
        approved_origins={'https://sdk.unit.invalid'}, api_key='offline-fixture-key')
    try:
        if too_many:
            with pytest.raises(EndpointFailure) as rejected:
                adapter.transcribe(row['remote_model'], wav(1), 'en')
            assert rejected.value.code == 'invalid_response'
        else:
            assert adapter.transcribe(row['remote_model'], wav(1), 'en') == [
                {'start': 0, 'end': 1, 'text': 'offline fixture'},
            ]
        assert len(calls) == 1
        assert adapter._guard.calls == 1
        assert adapter.contract == before == contract
    finally:
        adapter.close()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_other_protocols_keep_their_strict_schema(protocol):
    adapter = object.__new__(LiteLLMAdapter)
    adapter.protocol = protocol
    schema = {'type': 'object', 'properties': {'x': {'type': 'array',
        'items': {'type': 'string'}, 'maxItems': 100}}, 'required': ['x'],
        'additionalProperties': False}
    before = deepcopy(schema)
    result = adapter._schema('kept', schema)
    assert result == {'type': 'json_schema', 'json_schema': {
        'name': 'kept', 'strict': True, 'schema': before,
    }}
    assert schema == before
