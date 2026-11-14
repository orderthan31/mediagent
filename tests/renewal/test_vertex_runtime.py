"""Actual pinned SDK + actual google-auth, fake HTTP only."""
import io
import json
import socket
import sys
import wave
from pathlib import Path
import pytest
import httpx
ROOT=Path(__file__).resolve().parents[2]
for p in ('packages/shared','tools/models'):
    sys.path.insert(0,str(ROOT/p))

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket,'getaddrinfo',deny)

@pytest.fixture
def account():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    return json.dumps(dict(type='service_account', project_id='test-project', private_key_id='synthetic',
        private_key=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),
        client_email='test@test-project.iam.gserviceaccount.com',client_id='123', token_uri='https://oauth2.googleapis.com/token'))

@pytest.mark.parametrize('operation',['translation','structured_audio'])
@pytest.mark.parametrize('location',['global','us-central1'])
def test_real_sdk_text_audio(account,operation,location):
    from mideagent_model_tools.litellm_adapter import LiteLLMAdapter
    from video_service.vertex_config import vertex_endpoint
    endpoint=vertex_endpoint('test-project',location)
    seen=[]
    def send(r):
        seen.append(r)
        if r.url.host=='oauth2.googleapis.com':
            return httpx.Response(200,json={'access_token':'synthetic-token','expires_in':3600,'token_type':'Bearer'})
        assert str(r.url)==endpoint+'/models/gemini-2.5-flash:generateContent'
        assert r.headers['authorization']=='Bearer synthetic-token'
        body=json.loads(r.content)
        assert body['generationConfig']['temperature']==0.2
        if operation=='structured_audio':
            assert 'inlineData' in json.dumps(body) or 'inline_data' in json.dumps(body)
        output={'translations':['hello']} if operation=='translation' else {'segments':[{'start':0,'end':0.5,'text':'hello'}]}
        return httpx.Response(200,json={'candidates':[{'content':{'role':'model','parts':[{'text':json.dumps(output)}]},'finishReason':'STOP','index':0}], 'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':5,'totalTokenCount':15}})
    adapter=LiteLLMAdapter(endpoint,protocol='vertex_ai',contract={'version':1,'adapter':'litellm','provider':'vertex_ai','model':'gemini-2.5-flash','operation':operation,'options':{'temperature':0.2},'vertex_project':'test-project','vertex_location':location},transport=httpx.MockTransport(send),approved_origins={endpoint.split('/v1/')[0],'https://oauth2.googleapis.com'},api_key=account)
    try:
        if operation=='translation':
            assert json.loads(adapter.chat('gemini-2.5-flash',[{'role':'user','content':'hello'}]))==['hello']
        else:
            f=io.BytesIO()
            with wave.open(f,'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*32000)
            assert adapter.transcribe('gemini-2.5-flash',f.getvalue(),'en')[0]['text']=='hello'
        assert len(seen)==2 and adapter._guard.calls==1
        from mideagent_model_tools.endpoints import EndpointFailure
        with pytest.raises(EndpointFailure):
            adapter.chat('gemini-2.5-flash',[{'role':'user','content':'again'}]) if operation=='translation' else adapter.transcribe('gemini-2.5-flash',f.getvalue(),'en')
        assert len(seen)==2
    finally:
        adapter.close()


@pytest.mark.parametrize('mutation', ['region','model','header','missing-header'])
def test_guard_substitutions_never_send(mutation):
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from mideagent_model_tools.endpoints import EndpointFailure
    endpoint='https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/publishers/google'
    guard=_GuardedTransport(httpx.MockTransport(lambda r: pytest.fail('wire')), endpoint, '/models/exact:generateContent','token','exact',{})
    url=endpoint+'/models/exact:generateContent'
    headers={'authorization':'Bearer token'}
    if mutation=='region': url=url.replace('us-central1','europe-west1')
    if mutation=='model': url=url.replace('/exact:', '/other:')
    if mutation=='header': headers['authorization']='Bearer other'
    if mutation=='missing-header': headers={}
    with pytest.raises(EndpointFailure):
        guard.handle_request(httpx.Request('POST',url,headers=headers,json={}))
    assert guard.calls==0


@pytest.mark.parametrize('status',[302,429,500])
def test_guard_errors_are_single_and_sanitized(status):
    from mideagent_model_tools.litellm_adapter import _GuardedTransport
    from mideagent_model_tools.endpoints import EndpointFailure
    seen=[]
    def send(r):
        seen.append(r)
        return httpx.Response(status,content=b'private-provider-sentinel',headers={'location':'https://evil.invalid'})
    base='https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/publishers/google'
    guard=_GuardedTransport(httpx.MockTransport(send),base,'/models/exact:generateContent','token','exact',{})
    req=httpx.Request('POST',base+'/models/exact:generateContent',headers={'authorization':'Bearer token'},json={})
    with pytest.raises(EndpointFailure) as caught: guard.handle_request(req)
    assert 'private-provider-sentinel' not in str(vars(caught.value))
    with pytest.raises(EndpointFailure): guard.handle_request(req)
    assert len(seen)==1


def test_real_oauth_accounts_are_request_owned(account):
    import base64
    from urllib.parse import parse_qs
    from mideagent_model_tools.vertex_auth import acquire_token
    seen=[]
    def send(r):
        assertion=parse_qs(r.content.decode())['assertion'][0]
        encoded=assertion.split('.')[1]
        payload=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        seen.append(payload['iss'])
        assert payload['aud']=='https://oauth2.googleapis.com/token'
        assert payload['scope']=='https://www.googleapis.com/auth/cloud-platform'
        return httpx.Response(200,json={'access_token':'token-'+str(len(seen)),'expires_in':3600,'token_type':'Bearer'})
    other=json.loads(account);other['client_email']='other@test-project.iam.gserviceaccount.com'
    tokens=[acquire_token(s,transport=httpx.MockTransport(send),approved_origins={'https://oauth2.googleapis.com'}) for s in (account,json.dumps(other))]
    assert tokens==['token-1','token-2']
    assert seen==['test@test-project.iam.gserviceaccount.com','other@test-project.iam.gserviceaccount.com']
