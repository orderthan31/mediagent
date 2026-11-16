"""Exact-model parity: real catalog/contracts/SDK, synthetic auth and no network."""
import base64
from copy import deepcopy
import io
import json
import socket
import sys
import wave
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in ('packages/shared', 'tools/models'):
    sys.path.insert(0, str(ROOT / path))

from video_service.llm_contract import freeze_inference, validate_inference
from video_service.model_catalog import classify
from video_service.vertex_config import vertex_endpoint
from test_vertex_runtime import account

MODEL = 'gemini-3.8-flash'
DOCS = {
    'gemini': 'https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash',
    'vertex_ai': 'https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash',
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('outbound network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)


def catalog(provider, protocol=None, model=MODEL):
    return classify(provider, {'id': model, 'supportedGenerationMethods': ['generateContent']}, protocol or provider)


def pin(provider) -> dict:
    selected = catalog(provider)['profile_variants']['transcription']['profile']
    return dict(selected, protocol=provider, provider=provider, remote_model=MODEL,
                model_id='a' * 32, revision=7, connection_id='b' * 32,
                connection_revision=3, sha256='c' * 64, credential_ref='db:' + 'd' * 32,
                endpoint=vertex_endpoint('test-project', 'global') if provider == 'vertex_ai' else 'https://generativelanguage.googleapis.com/v1beta',
                **({'vertex_project': 'test-project', 'vertex_location': 'global'} if provider == 'vertex_ai' else {}))


@pytest.mark.parametrize('provider', ['gemini', 'vertex_ai'])
def test_exact_primary_evidence_and_explicit_variant(provider):
    result = catalog(provider)
    variant = result['profile_variants']['transcription']
    assert result['runtime_uses'] == ['translation']
    assert variant['runtime_uses'] == ['transcription', 'translation']
    assert DOCS[provider] in variant['evidence']
    assert result['id'] == MODEL and result['inference_verified'] is False
    assert 'speech_recognition' not in result['profile']['capabilities']
    frozen = freeze_inference(pin(provider), 'transcription', '{"reasoning_effort":"low","max_tokens":1024}')
    assert frozen['operation'] == 'structured_audio'
    assert frozen['model'] == MODEL and frozen['revision'] == 7
    assert validate_inference(pin(provider), frozen) == frozen
    with pytest.raises(ValueError):
        validate_inference({**pin(provider), 'revision': 8}, frozen)
    with pytest.raises(ValueError):
        freeze_inference({**pin(provider), **result['profile']}, 'transcription')


@pytest.mark.parametrize('provider,protocol', [('gemini', 'vertex_ai'), ('vertex_ai', 'gemini'), ('vertex_ai', 'openai'), ('gemini', 'openai_compatible')])
def test_wrong_protocol_cannot_borrow_sdk_capabilities(provider, protocol):
    result = catalog(provider, protocol)
    assert result['profile'] is None
    assert result['runtime_uses'] == []
    assert not result.get('profile_variants')
    assert result['classification_status'] == 'unsupported'


@pytest.mark.parametrize('provider', ['gemini', 'vertex_ai'])
def test_unknown_ids_and_missing_sdk_evidence_do_not_gain_vertex_audio(provider, monkeypatch):
    from mideagent_model_tools import sdk_metadata
    assert catalog(provider, model='gemini-unknown-not-evidenced')['profile'] is None
    if provider == 'vertex_ai':
        monkeypatch.setattr(sdk_metadata, 'capability_map', lambda: {})
        assert catalog(provider)['profile'] is None


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0' * 32000)
    return out.getvalue()


@pytest.mark.parametrize('provider', ['gemini', 'vertex_ai'])
@pytest.mark.parametrize('effort', ['low', 'medium', 'high'])
def test_actual_frozen_runtime_sdk_audio_wire(provider, effort, account):
    from video_service.postgres.transcription import TranscriptionRuntime
    selected = pin(provider)
    selected['inference'] = freeze_inference(selected, 'transcription', json.dumps({'reasoning_effort': effort, 'max_tokens': 1024}))
    original = deepcopy(selected)
    audio, seen = wav(), []
    segments = [{'start': 0, 'end': 0.5, 'text': 'hello'}]

    def send(request):
        seen.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'synthetic-token', 'expires_in': 3600, 'token_type': 'Bearer'})
        assert str(request.url) == selected['endpoint'] + '/models/' + MODEL + ':generateContent'
        if provider == 'vertex_ai':
            assert request.headers['authorization'] == 'Bearer synthetic-token'
            assert not request.headers.get('x-goog-api-key')
        else:
            assert request.headers['x-goog-api-key'] == 'synthetic-key'
            assert not request.headers.get('authorization')
        body = json.loads(request.content)
        config = body['generationConfig']
        assert not {'temperature', 'topP', 'topK', 'candidateCount', 'candidate_count'} & set(config)
        assert config.get('maxOutputTokens', config.get('max_output_tokens')) == 1024
        thinking = config.get('thinkingConfig', config.get('thinking_config'))
        assert thinking.get('thinkingLevel', thinking.get('thinking_level')).lower() == effort
        schema = config.get('responseSchema', config.get('responseJsonSchema', config.get('response_schema', config.get('response_json_schema'))))
        assert schema['properties']['segments']['items']['properties']['start']['type'].lower() == 'number'
        parts = body['contents'][0]['parts']
        inline = [part.get('inlineData', part.get('inline_data')) for part in parts if 'inlineData' in part or 'inline_data' in part]
        assert len(inline) == 1
        assert base64.b64decode(inline[0]['data']) == audio
        assert inline[0].get('mimeType', inline[0].get('mime_type')) == 'audio/wav'
        return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [{'text': json.dumps({'segments': segments})}]}, 'finishReason': 'STOP', 'index': 0}], 'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5, 'totalTokenCount': 15}})

    runtime = object.__new__(TranscriptionRuntime)
    runtime.transport_factory = lambda: httpx.MockTransport(send)
    runtime.approved_origins = {selected['endpoint'].split('/v1')[0], 'https://oauth2.googleapis.com'}
    adapter = runtime.make_adapter(selected, account if provider == 'vertex_ai' else 'synthetic-key')
    try:
        assert adapter.transcribe(MODEL, audio, 'en') == segments
        assert adapter._guard.calls == 1
        assert len(seen) == (2 if provider == 'vertex_ai' else 1)
        assert selected == original
    finally:
        adapter.close()


@pytest.mark.parametrize('provider', ['gemini', 'vertex_ai'])
@pytest.mark.parametrize('options', [{'temperature': 1}, {'top_p': 0.8}, {'reasoning_effort': 'minimal'}, {'top_k': 1}, {'candidate_count': 1}])
def test_unsupported_options_fail_before_any_wire(provider, options, account):
    from mideagent_model_tools.litellm_adapter import LiteLLMAdapter
    selected = pin(provider)
    with pytest.raises(ValueError):
        contract = freeze_inference(selected, 'transcription', json.dumps(options))
        LiteLLMAdapter(selected['endpoint'], protocol=provider, contract=contract,
                       transport=httpx.MockTransport(lambda request: pytest.fail('wire')),
                       approved_origins={selected['endpoint'].split('/v1')[0], 'https://oauth2.googleapis.com'},
                       api_key=account if provider == 'vertex_ai' else 'synthetic-key')


@pytest.mark.parametrize('provider', ['gemini', 'vertex_ai'])
def test_catalog_proofs_actual_registration_revision_fences(provider, account, monkeypatch):
    """Actual seal/query/save logic; only persistence is an in-memory SQL fake."""
    from contextlib import nullcontext
    from types import SimpleNamespace
    from video_service.model_catalog import ModelCatalog
    from video_service.postgres import Conflict
    from video_service.postgres.credentials import CredentialStore
    from video_service.postgres.registry import Registry

    selected = pin(provider)
    owner, cid, mid = 'e' * 32, selected['connection_id'], selected['model_id']
    config: dict = dict(selected, revision=3)
    connection = {'active': True, 'revision': 3}
    versions, model_parent = {}, {'revision': 0, 'state_revision': 0}

    class FakeSQL:
        def execute(self, sql, params):
            if sql.startswith('INSERT INTO model_revisions'):
                columns = sql.split('(', 1)[1].split(')', 1)[0].split(',')
                row = dict(zip(columns, deepcopy(params)))
                versions[row['revision']] = row
            elif sql.startswith('UPDATE registered_models SET revision='):
                model_parent.update(revision=params[0], state_revision=model_parent['state_revision'] + 1)
            elif sql.startswith('SELECT * FROM model_revisions'):
                self.row = versions.get(params[-1])
            else:
                assert sql.startswith('SELECT 1 FROM serving_connections')
            return self

        def fetchone(self):
            return self.row

    database = SimpleNamespace(connection=lambda: nullcontext(FakeSQL()))
    registry = Registry(database)
    monkeypatch.setattr(registry, '_connection', lambda *args: (connection, config))
    def lock(db, table, who, identity, revision):
        assert table == 'registered_models' and who == owner and identity == mid
        if revision != model_parent['state_revision']:
            raise Conflict('stale revision')
        return model_parent
    monkeypatch.setattr(registry, '_lock', lock)
    monkeypatch.setattr(registry, '_model', lambda *args: deepcopy(versions))
    credentials = CredentialStore(database, b's' * 32)
    monkeypatch.setattr(credentials, 'resolve', lambda *args: account if provider == 'vertex_ai' else 'synthetic-key')
    requests = []
    def send(request):
        requests.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'synthetic-token', 'expires_in': 3600, 'token_type': 'Bearer'})
        assert request.method == 'GET'
        if provider == 'vertex_ai':
            return httpx.Response(200, json={'publisherModels': [{'name': 'publishers/google/models/' + MODEL}]})
        return httpx.Response(200, json={'models': [{'name': 'models/' + MODEL, 'supportedGenerationMethods': ['generateContent']}]})
    result = ModelCatalog(registry, credentials, transport=httpx.MockTransport(send),
                          approved_origins={'https://aiplatform.googleapis.com', 'https://oauth2.googleapis.com'}).query(owner, cid, 3)
    base = result['models'][0]
    variant = base['profile_variants']['transcription']
    text_proof = credentials.open_catalog_entry(owner, cid, base['registration_token'])
    audio_proof = credentials.open_catalog_entry(owner, cid, variant['registration_token'])
    assert text_proof['profile'] != audio_proof['profile']
    with pytest.raises(ValueError):
        credentials.open_catalog_entry(owner, 'f' * 32, variant['registration_token'])

    def save(profile, proof, revision):
        return registry.save_model(owner, mid, revision=revision, name='synthetic selection', model=MODEL,
                                   connection_id=cid, connection_revision=3, catalog_binding=proof, **profile)
    save(base['profile'], text_proof, 0)
    previous = deepcopy(versions[1])
    with pytest.raises(ValueError):
        save(variant['profile'], text_proof, 1)
    assert set(versions) == {1}
    save(variant['profile'], audio_proof, 1)
    assert versions[1] == previous and set(versions) == {1, 2}
    assert 'speech_recognition' not in versions[1]['capabilities']
    assert 'speech_recognition' in versions[2]['capabilities']
    with pytest.raises(Conflict):
        save(variant['profile'], audio_proof, 1)
    config['sha256'] = 'f' * 64
    with pytest.raises(Conflict):
        save(variant['profile'], audio_proof, 2)
    assert set(versions) == {1, 2}
    assert [request.method for request in requests] == (['POST', 'GET'] if provider == 'vertex_ai' else ['GET'])


@pytest.mark.parametrize('extra', [{'temperature': 0.5}, {'temperature': True}, {'topP': 0.8}, {'topK': 4}, {'candidateCount': 1}])
def test_wire_rejects_other_injected_options_before_send(extra):
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from mideagent_model_tools.endpoints import EndpointFailure
    base = pin('vertex_ai')['endpoint']
    guard = _GuardedTransport(httpx.MockTransport(lambda request: pytest.fail('wire')), base,
                              '/models/' + MODEL + ':generateContent', 'synthetic-token', MODEL, {})
    guard.schema = {'type': 'object', 'properties': {'segments': {'type': 'array'}}}
    with pytest.raises(EndpointFailure):
        guard.handle_request(httpx.Request('POST', base + '/models/' + MODEL + ':generateContent',
                             headers={'authorization': 'Bearer synthetic-token'},
                             json={'generationConfig': {'responseSchema': guard.schema, **extra}}))
    assert guard.calls == 0


@pytest.mark.parametrize('model', [MODEL, 'gemini-2.5-flash', 'gemini-unknown-not-evidenced'])
def test_wire_default_removal_is_exact_and_preserves_schema_auth_timeout(model):
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    base = pin('vertex_ai')['endpoint']
    seen = []
    def send(request):
        seen.append(request)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{}'}]}, 'finishReason': 'STOP'}]})
    guard = _GuardedTransport(httpx.MockTransport(send), base, '/models/' + model + ':generateContent',
                              'synthetic-token', model, {'timeout': 91})
    guard.schema = {'type': 'object', 'properties': {'segments': {'type': 'array'}}}
    payload = {'contents': [{'parts': [{'text': 'synthetic'}]}], 'generationConfig': {'responseSchema': guard.schema, 'temperature': 1.0}}
    guard.handle_request(httpx.Request('POST', base + '/models/' + model + ':generateContent',
                         headers={'authorization': 'Bearer synthetic-token'}, json=payload))
    expected = deepcopy(payload)
    if model == MODEL:
        del expected['generationConfig']['temperature']
    assert json.loads(seen[0].content) == expected
    assert int(seen[0].headers['content-length']) == len(seen[0].content)
    assert seen[0].headers['authorization'] == 'Bearer synthetic-token'
    assert seen[0].extensions['mideagent_timeout_seconds'] == 91
    assert payload['generationConfig']['temperature'] == 1.0
