"""Model taxonomy and task compatibility require explicit declared abilities."""
from uuid import uuid4
import pytest
from video_service.model_profile import validate_profile, supports_role
from video_service.postgres.registry import Registry
from test_foundation import db, admin, app_client, login


def profile(kind='text'):
    if kind == 'tts':
        return dict(model_types=['tts'], input_modalities=['text'], output_modalities=['audio'], capabilities=['speech_synthesis'])
    if kind == 'speech_recognition':
        return dict(model_types=[kind], input_modalities=['audio'], output_modalities=['text'], capabilities=[kind])
    return dict(model_types=['text'], input_modalities=['text'], output_modalities=['text'], capabilities=['text_generation'])


def test_model_profile_role_separation_and_fail_closed():
    text = validate_profile(**profile())
    tts = validate_profile(**profile('tts'))
    stt = validate_profile(**profile('speech_recognition'))
    assert supports_role(text, 'translation') and not supports_role(text, 'transcription')
    assert not supports_role(text, 'decision')
    assert supports_role(tts, 'tts') and not supports_role(tts, 'translation')
    assert supports_role(stt, 'transcription') and not supports_role(stt, 'translation')
    assert not supports_role({'uses': ['transcription', 'translation']}, 'translation')
    decision = {**text, 'model_types': ['text', 'decision'], 'capabilities': ['text_generation', 'structured_output']}
    assert supports_role(validate_profile(**decision), 'decision')
    with pytest.raises(ValueError):
        validate_profile(**{**text, 'model_types': ['translation']})
    with pytest.raises(ValueError):
        validate_profile(**{**tts, 'output_modalities': ['text']})
    with pytest.raises(ValueError):
        validate_profile(**{**text, 'model_types': ['decision']})


def test_tts_metadata_is_not_text_adapter_execution_and_revisions_pin(db, admin):
    registry, owner = Registry(db), admin[0]['id']
    cid, mid = uuid4().hex, uuid4().hex
    registry.save_connection(owner, cid, revision=0, name='Synthetic endpoint', provider='openai_compatible', protocol='openai_compatible', endpoint='http://127.0.0.1:9/v1')
    with app_client(db) as client:
        login(client, admin)
        payload = dict(revision=0, name='Synthetic TTS', model='arbitrary-id-with-no-name-inference', connection_id=cid, connection_revision=1, **profile('tts'))
        saved = client.put('/api/settings/registered-models/' + mid, json=payload)
        assert saved.status_code == 200
        assert saved.json()['versions']['1']['model_types'] == ['tts']
        payload.update(revision=1, **profile())
        assert client.put('/api/settings/registered-models/' + mid, json=payload).status_code == 200
        versions = client.get('/api/settings/registered-models').json()['models'][0]['versions']
        assert versions['1']['output_modalities'] == ['audio']
        assert versions['2']['output_modalities'] == ['text']
        assert versions['1']['sha256'] != versions['2']['sha256']
        metadata = client.post('/api/settings/registered-models/compatibility', json={'connection_id': cid, 'model': payload['model']}).json()
        assert metadata['verified'] is False and metadata['adapter_capabilities'] == ['text_generation']
        assert client.get('/api/capabilities').json()['model_network_enabled'] is False
