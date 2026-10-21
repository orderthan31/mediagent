"""Normal product auth/CSRF against an opt-in isolated control mailbox."""
import os
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from app.renewal import create_app


def test_product_endpoint_requires_admin_csrf_and_idempotent_request():
    assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
    db=Database(os.environ['MIDEAGENT_CONTROL_HTTP_DSN']);db.migrate()
    store=RemoteControl(db)
    slot=uuid4().hex
    store.provision('analyze','c'*64,[slot])
    store.publish('analyze','c'*64,[{'id':slot,'running':False,'state':'stopped','received_at':None}])
    app=create_app(db,allowed_origins=('http://testserver',),secure_cookies=False,remote_control=store)
    with TestClient(app) as client:
        assert client.get('/api/admin/agents/analyze').status_code==401
        password=secrets.token_urlsafe(24)
        assert client.post('/api/auth/bootstrap',json={'username':'control-admin','password':password}).status_code==201
        response=client.post('/api/auth/login',json={'username':'control-admin','password':password})
        assert response.status_code==200
        csrf=response.json()['csrf_token']
        body={'revision':0,'enabled':True,'replicas':1,'request_id':uuid4().hex}
        endpoint='/api/admin/agents/analyze/configuration'
        assert client.put(endpoint,json=body).status_code==403
        headers={'Origin':'http://testserver','X-CSRF-Token':csrf}
        assert client.put(endpoint,json={**body,'container_id':'f'*64},headers=headers).status_code==422
        out_of_capacity=client.put(endpoint,json={**body,'replicas':2},headers=headers)
        assert out_of_capacity.status_code==422
        first=client.put(endpoint,json=body,headers=headers)
        assert first.status_code==200
        assert client.put(endpoint,json=body,headers=headers).json()==first.json()
        changed={**body,'request_id':uuid4().hex}
        assert client.put(endpoint,json=changed,headers=headers).status_code==409
        member_password=secrets.token_urlsafe(24)
        assert client.post('/api/accounts',json={'username':'control-member','password':member_password},headers=headers).status_code==201
        member=client.post('/api/auth/login',json={'username':'control-member','password':member_password})
        assert member.status_code==200
        member_headers={'Origin':'http://testserver','X-CSRF-Token':member.json()['csrf_token']}
        assert client.put(endpoint,json=body,headers=member_headers).status_code==403
        assert client.get('/api/admin/agents/analyze').status_code==403
