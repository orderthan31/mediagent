"""Disposable translation contracts, not provider authentication or quality."""
import json
from uuid import uuid4

from video_service.renewal_contracts import validate


def translation_graph(ref, fallbacks=()):
    return {
        'catalog_version': 1, 'revision': 0, 'name': 'Registered translation',
        'inputs': {'transcript': 'transcript'},
        'nodes': [{'id': 'translate', 'type': 'translate',
                   'position': {'x': 200, 'y': 50}, 'options': {},
                   'model_ref': ref, 'fallback_refs': list(fallbacks)}],
        'edges': [{'id': 'e', 'source': {'node': '$input', 'port': 'transcript'},
                   'target': {'node': 'translate', 'port': 'transcript'}}],
    }


def test_optional_fallback_contract_has_exact_unique_finite_refs():
    primary = {'model_id': uuid4().hex, 'revision': 1}
    fallback = {'model_id': uuid4().hex, 'revision': 2}
    graph = translation_graph(primary, [fallback])
    assert validate(graph)['valid']
    graph['nodes'][0]['fallback_refs'] = []
    assert validate(graph)['valid']
    graph['nodes'][0]['fallback_refs'] = [primary]
    assert not validate(graph)['valid']
    graph['nodes'][0]['fallback_refs'] = [fallback] * 4
    assert not validate(graph)['valid']


def test_gemini_native_adapter_uses_header_and_generate_content():
    import httpx
    import video_service.model_endpoints as endpoints

    adapter_type = getattr(endpoints, 'GeminiTextAdapter', None)
    assert adapter_type is not None, 'Gemini native adapter is not implemented'
    calls = []

    def wire(request):
        calls.append(request)
        assert str(request.url) == 'https://synthetic.invalid/v1beta/models/fixture-gemini:generateContent'
        assert request.headers['x-goog-api-key'] == 'synthetic-header-key'
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        assert body['systemInstruction']['parts'][0]['text'] == 'Translate'
        assert body['contents'][0]['parts'][0]['text'] == 'Hello'
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '안녕'}]}}]})

    adapter = adapter_type('https://synthetic.invalid/v1beta', transport=httpx.MockTransport(wire),
                           approved_origins={'https://synthetic.invalid'}, api_key='synthetic-header-key')
    try:
        assert adapter.chat('fixture-gemini', [{'role': 'system', 'content': 'Translate'}, {'role': 'user', 'content': 'Hello'}]) == '안녕'
    finally:
        adapter.close()
    assert len(calls) == 1
