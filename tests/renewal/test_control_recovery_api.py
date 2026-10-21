"""Real ASGI auth, administrator/CSRF admission and PG-backed host completion."""
import os,secrets
from uuid import uuid4
from fastapi.testclient import TestClient
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_recovery import ControlRecovery
from app.renewal import create_app


def test_recovery_is_opt_in_admin_csrf_and_api_admission_is_not_completion():
    assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
    db=Database(os.environ['MIDEAGENT_REVIEW_HTTP_DSN']);db.migrate();store=RemoteControl(db);recovery=ControlRecovery(store)
    app=create_app(db,allowed_origins=('http://testserver',),secure_cookies=False,remote_control=store,control_recovery=recovery)
    endpoint='/api/admin/agents/analyze/recovery'
    with TestClient(app) as client:
        assert client.get(endpoint).status_code==401
        password=secrets.token_urlsafe(32)
        assert client.post('/api/auth/bootstrap',json={'username':'review-http-admin','password':password}).status_code==201
        login=client.post('/api/auth/login',json={'username':'review-http-admin','password':password});assert login.status_code==200
        headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']}
        wid=uuid4().hex;store.provision('analyze','c'*64,[wid]);store.publish('analyze','c'*64,[{'id':wid,'running':False,'state':'stopped','boot_id':uuid4().hex,'exit_code':0,'restart_policy':'no','started_at':'2026-01-01T00:00:00Z'}])
        assert client.get(endpoint).status_code==200
        assert client.post(endpoint+'/preview',json={}).status_code==403
        assert client.post(endpoint+'/preview',json={'container_id':'a'*64},headers=headers).status_code==422
        member_password=secrets.token_urlsafe(32)
        assert client.post('/api/accounts',json={'username':'review-http-member','password':member_password},headers=headers).status_code==201
        member=client.post('/api/auth/login',json={'username':'review-http-member','password':member_password});assert member.status_code==200
        member_headers={'Origin':'http://testserver','X-CSRF-Token':member.json()['csrf_token']}
        assert client.get(endpoint).status_code==403
        assert client.post(endpoint+'/preview',json={},headers=member_headers).status_code==403
