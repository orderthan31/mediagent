"""Offline synthetic service-account and immutable inference contracts."""
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from video_service.vertex_config import parse_service_account, vertex_endpoint
from video_service.llm_contract import freeze_inference, validate_inference

@pytest.fixture(scope='module')
def account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return dict(type='service_account', project_id='test-project', private_key_id='a'*40,
                private_key=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
                client_email='test@test-project.iam.gserviceaccount.com', client_id='123456789',
                token_uri='https://oauth2.googleapis.com/token')

def test_offline_account_and_exact_utf8_boundary(account):
    raw = json.dumps(account)
    assert parse_service_account(raw) == account
    assert parse_service_account(raw + ' '*(32768-len(raw.encode()))) == account
    with pytest.raises(ValueError, match='^invalid_service_account$'):
        parse_service_account(raw + ' '*(32769-len(raw.encode())))

@pytest.mark.parametrize('field,value', [('type','authorized_user'), ('token_uri','https://evil.test/token'), ('universe_domain','evil.test'), ('private_key','SECRET'), ('client_email',42), ('unknown','SECRET')])
def test_reject_invalid_without_echo(account, field, value):
    with pytest.raises(ValueError, match='^invalid_service_account$'):
        parse_service_account(json.dumps({**account,field:value}))

def test_duplicates(account):
    with pytest.raises(ValueError, match='^invalid_service_account$'):
        parse_service_account(json.dumps(account)[:-1]+',"type":"service_account"}')

@pytest.mark.parametrize('bits',[1024])
def test_small_rsa_rejected(account,bits):
    key=rsa.generate_private_key(public_exponent=65537,key_size=bits)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    with pytest.raises(ValueError,match='^invalid_service_account$'):
        parse_service_account(json.dumps({**account,'private_key':pem}))

@pytest.mark.parametrize('raw',['[]','null','{}','{"private_key":"NEVER-ECHO"}', '\ud800'])
def test_malformed_generic(raw):
    with pytest.raises(ValueError,match='^invalid_service_account$'): parse_service_account(raw)

def test_explicit_metadata_and_ordinary_shape():
    from mideagent_model_tools.endpoints import connection_contract
    from video_service.vertex_config import vertex_metadata
    with pytest.raises(ValueError): connection_contract('vertex_ai')
    with pytest.raises(ValueError): connection_contract('vertex_ai',endpoint='https://evil.test',vertex_project='test-project',vertex_location='global')
    with pytest.raises(ValueError): connection_contract('gemini',vertex_project='test-project')
    assert connection_contract('vertex_ai',vertex_project='test-project',vertex_location='global') == ('vertex_ai',vertex_endpoint('test-project','global'))
    assert vertex_metadata({'provider':'gemini','protocol':'gemini','vertex_project':None,'vertex_location':None}) == {}

def test_endpoint():
    assert vertex_endpoint('test-project','global') == 'https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/publishers/google'
    assert vertex_endpoint('test-project','us-central1').startswith('https://us-central1-aiplatform.googleapis.com/')
    for p,l in [('bad/path','global'),('test-project','evil.test'),('test-project','us-central1/../global')]:
        with pytest.raises(ValueError): vertex_endpoint(p,l)

def row(protocol='vertex_ai'):
    return dict(protocol=protocol,provider=protocol,remote_model='gemini-test',model_id='a'*32,revision=1, model_types=['multimodal'],input_modalities=['audio','text'],output_modalities=['text'],capabilities=['text_generation','structured_output','speech_recognition'],vertex_project='test-project',vertex_location='global')

def test_pins_conditional_and_tamper_detection():
    v=row(); c=freeze_inference(v,'translation')
    assert c['vertex_project']=='test-project' and c['vertex_location']=='global'
    assert 'vertex_project' not in freeze_inference(row('gemini'),'translation')
    with pytest.raises(ValueError): validate_inference({**v,'vertex_location':'us-central1'},c)
    assert freeze_inference(v,'transcription')['operation']=='structured_audio'
    with pytest.raises(ValueError): freeze_inference(v,'transcription','{"audio_api":"audio_transcription"}')
