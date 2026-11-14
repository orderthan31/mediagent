"""No provider calls: pure manifests/API and explicit disposable PG lifecycle."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.unit_recovery_routes import mount_unit_recovery_routes
from video_service.canonical import canonical, digest
from video_service.content_store import ContentStore
from video_service.postgres import Conflict
from video_service.postgres.execution import Execution
from video_service.postgres.unit_recovery import RoleUnitRecovery
from video_service.role_policy import model_binding
from video_service.transcript_batches import split_transcript
from video_service.unit_recovery import build_manifest
from test_foundation import db, admin, login


def evidence():
    source = [dict(id=i, start=i*2, end=i*2+1, text='source') for i in range(201)]
    pin = dict(model_id='b'*32, revision=1, credential_ref='private-key-reference', endpoint='https://private.invalid')
    task = dict(version=2, role_policy_version=2, task_id='a'*32, role='translation',
                models=[model_binding(pin)], source_language='en', target_language='ko',
                transcript={'bytes': len(canonical(source)), 'sha256': digest(source)},
                batch_policy='bounded_100x16k_v1', max_calls=3)
    batches = list(split_transcript(source, policy_version=2))
    calls = [dict(chunk_index=i, input_sha256=batches[i].sha256, model=task['models'][0],
                  status='completed' if i == 0 else 'failed',
                  response=json.dumps(['translated'] * len(batches[i].segments)) if i == 0 else None,
                  error_code=None if i == 0 else 'invalid_response') for i in range(2)]
    return source, pin, task, calls


def test_real_preview_hides_pins_and_keeps_suffix():
    source, pin, task, calls = evidence()
    manifest = build_manifest(task, source, calls)
    facts = ({'revision': 7}, {'id': 'c'*32}, {'frozen_candidates': [pin]}, None, {'frozen': True}, manifest, None)
    body = dict(job_revision=7, recovery_revision=0, context_sha256=digest(facts[4]),
                decisions=[dict(unit_index=1, action='retry')])
    service = RoleUnitRecovery(None)
    result = service._preview(facts, body)
    assert not result['ready'] and 'unit:2:unresolved' in result['blocked_reasons']
    assert result['additional_call_limit'] == 1
    assert 'private-key' not in str(result) and 'private.invalid' not in str(result)
    assert 'pin_sha256' not in str(result)
    body['decisions'].append(dict(unit_index=2, action='skip'))
    result = service._preview(facts, body)
    assert result['ready']
    assert result['preview_sha256'] == digest({k:v for k,v in result.items() if k != 'preview_sha256'})


def test_api_requires_auth_strict_approval_and_continue_order(monkeypatch):
    events = []
    def owner():
        return 'owner'
    app = FastAPI()
    runtime = SimpleNamespace(accept_role_recovery=lambda *args: events.append('adopt') or {'ok': True})
    service = mount_unit_recovery_routes(app, runtime, Depends(owner), continue_job=lambda *a: events.append('dispatch'))
    monkeypatch.setattr(service, 'inspect', lambda *a: {'access': {'can_manage': True}})
    monkeypatch.setattr(service, 'preview', lambda *a: events.append('preview') or {'ok': True})
    with TestClient(app) as client:
        base = '/api/renewal/jobs/j/runs/r/unit-recovery'
        body = dict(job_revision=1, recovery_revision=0, context_sha256='a'*64, decisions=[])
        assert client.post(base+'/preview', json=body).status_code == 200
        assert events == ['preview']
        assert client.post(base+'/decisions', json={**body, 'request_id':'r','preview_sha256':'b'*64,'approve_calls':1}).status_code == 422
        assert client.post(base+'/continue', json={'request_id':'r'}).status_code == 200
        assert events == ['preview','adopt','dispatch']
        def denied():
            raise HTTPException(401, 'login_required')
        app.dependency_overrides[owner] = denied
        assert client.get(base).status_code == 401
        assert client.post(base+'/execute', json={'request_id':'r'}).status_code == 401


@pytest.fixture
def seeded(db, admin, tmp_path):
    owner = admin[0]['id']
    runtime = Execution(db, ContentStore(tmp_path))
    source, pin, task, calls = evidence()
    asset, workflow, job, run = [uuid4().hex for _ in range(4)]
    task['task_id'] = run
    ref = runtime.store.put(owner, [canonical(source)], 'transcript')
    command = dict(protocol_version=1, run_id=job, attempt_id=run, generation=1,
                   agent={'id':'translate'}, inputs={'transcript':ref})
    envelope = dict(version=1, role='translation', task=task)
    with db.connection() as c:
        c.execute('INSERT INTO assets(owner_id,id,filename,storage_key,bytes) VALUES(%s,%s,%s,%s,%s)', (owner,asset,'test','test',1))
        c.execute('INSERT INTO workflows(owner_id,id,revision) VALUES(%s,%s,1)', (owner,workflow))
        c.execute('INSERT INTO workflow_revisions(owner_id,workflow_id,revision,name,definition,sha256) VALUES(%s,%s,1,%s,%s,%s)', (owner,workflow,'test',Jsonb({}),digest({})))
        c.execute("INSERT INTO jobs(owner_id,id,asset_id,workflow_id,workflow_revision,status,snapshot,snapshot_sha256,active_claim_id,workflow_owner_id) VALUES(%s,%s,%s,%s,1,'running',%s,%s,%s,%s)", (owner,job,asset,workflow,Jsonb({}),digest({}),'claim',owner))
        c.execute("INSERT INTO node_runs(owner_id,job_id,id,node_id,agent_revision,attempt,generation,status,input_sha256,settings_sha256,node_type,request,request_sha256,claim_id,lease_owner,lease_expires_at) VALUES(%s,%s,%s,'translate','1',1,1,'running',%s,%s,'translate',%s,%s,'claim','old-worker',now()-interval '1 day')", (owner,job,run,digest({}),digest({}),Jsonb(command),digest(command)))
        c.execute("INSERT INTO model_role_tasks(owner_id,job_id,attempt_id,task_id,generation,request_sha256,envelope,envelope_sha256,frozen_candidates,phase) VALUES(%s,%s,%s,%s,1,%s,%s,%s,%s,'held')", (owner,job,run,run,digest(command),Jsonb(envelope),digest(envelope),Jsonb([pin])))
        for call in calls:
            c.execute('INSERT INTO model_role_tool_calls(task_id,chunk_index,input_sha256,model,status,response,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s)', (run,call['chunk_index'],call['input_sha256'],Jsonb(call['model']),call['status'],Jsonb(call['response']) if call['response'] else None,call['error_code']))
    return runtime, owner, job, run, source


def approval(service, owner, job, run, decisions):
    state = service.inspect(owner,job,run)
    body = {k: state[k] for k in ('job_revision','recovery_revision','context_sha256')}
    body['decisions'] = decisions
    preview = service.preview(owner,job,run,body)
    return {**body, 'request_id': uuid4().hex,'preview_sha256':preview['preview_sha256'],'approve_calls':True}


def test_native_manual_adoption_atomic_checks_and_applied_replay(seeded):
    runtime, owner, job, run, source = seeded
    service = RoleUnitRecovery(runtime)
    with runtime.database.connection() as c:
        before = c.execute('SELECT * FROM node_runs WHERE id=%s',(run,)).fetchone()
        root = c.execute('SELECT * FROM model_role_tasks WHERE task_id=%s',(run,)).fetchone()
    body = approval(service,owner,job,run,[{'unit_index':1,'action':'manual','value':[{**r,'text':'manual'} for r in source[100:200]]},{'unit_index':2,'action':'skip'}])
    state = service.decide(owner,job,run,body)
    assert state['recovery']['can_continue']
    assert service.inspect(owner,job,run)['decisions'] == body['decisions']
    assert service.decide(owner,job,run,body) == state
    with pytest.raises(Conflict):
        service.decide(owner,job,run,{**body,'approve_calls':False})
    with pytest.raises(PermissionError):
        service.preview('other',job,run,{k:v for k,v in body.items() if k not in {'request_id','approve_calls','preview_sha256'}})
    prepared = service.prepare_adoption(owner,job,run,body['request_id'])
    rows = json.loads(runtime.store.read(owner,prepared['outputs']['transcript']))
    assert len(rows) == 200 and rows[100]['text'] == 'manual'
    with pytest.raises(RuntimeError, match='rollback'):
        with runtime.database.connection() as c:
            service.mark_applied_in(c,prepared['recovery_id'],'e'*64)
            raise RuntimeError('rollback')
    with runtime.database.connection() as c:
        assert c.execute('SELECT status FROM model_role_unit_recoveries WHERE id=%s',(prepared['recovery_id'],)).fetchone()['status'] == 'approved'
        jobrow = c.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE',(job,)).fetchone()
        runrow = c.execute('SELECT * FROM node_runs WHERE id=%s FOR UPDATE',(run,)).fetchone()
        assert runrow == before
        assert c.execute('SELECT * FROM model_role_tasks WHERE task_id=%s',(run,)).fetchone() == root
        service.check_adoption_in(c,owner,jobrow,runrow,prepared['recovery_id'],prepared['context_sha256'])
        service.mark_applied_in(c,prepared['recovery_id'],'f'*64)
        c.execute('UPDATE jobs SET revision=revision+1 WHERE id=%s',(job,))
    assert service.prepare_adoption(owner,job,run,body['request_id']) == prepared


def test_native_concurrent_same_request_has_one_recovery(seeded):
    from concurrent.futures import ThreadPoolExecutor
    runtime, owner, job, run, source = seeded
    service = RoleUnitRecovery(runtime)
    body = approval(service,owner,job,run,[{'unit_index':1,'action':'manual','value':[{**r,'text':'manual'} for r in source[100:200]]},{'unit_index':2,'action':'skip'}])
    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(lambda _: service.decide(owner,job,run,body), range(2)))
    assert states[0]['recovery']['id'] == states[1]['recovery']['id']
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) AS n FROM model_role_unit_recoveries WHERE run_id=%s',(run,)).fetchone()['n'] == 1


def test_native_authenticated_api_csrf_and_shared_read(seeded, db, admin):
    from app.renewal import create_app
    from video_service.postgres.accounts import Accounts
    runtime, owner, job, run, _ = seeded
    app = create_app(db, allowed_origins=('http://testserver',), secure_cookies=False, content_store=runtime.store)
    base = f'/api/renewal/jobs/{job}/runs/{run}/unit-recovery'
    with TestClient(app) as client:
        assert client.get(base).status_code == 401
        login(client, admin)
        state = client.get(base)
        assert state.status_code == 200 and state.json()['access']['can_manage']
        assert client.post(base+'/execute',json={'request_id':'r'},headers={'X-CSRF-Token':''}).status_code == 403
        reader = Accounts(db).create('unit-reader', admin[1], actor_id=owner)
        login(client, (reader, admin[1]))
        state = client.get(base)
        assert state.status_code == 200 and not state.json()['access']['can_manage']
        assert client.post(base+'/execute',json={'request_id':'r'}).status_code == 403


def test_native_attempt_sending_is_durable_nonrepeatable_and_terminal_immutable(seeded):
    runtime, owner, job, run, source = seeded
    service = RoleUnitRecovery(runtime)
    body = approval(service,owner,job,run,[{'unit_index':1,'action':'retry'},{'unit_index':2,'action':'skip'}])
    state = service.decide(owner,job,run,body)
    attempt = next(a['id'] for a in state['units'][1]['attempts'] if a['origin'] == 'recovery')
    with pytest.raises(Conflict,match='executor_unavailable'):
        service.execute(owner,job,run,body['request_id'])
    grant = service.begin_attempt(attempt,body['context_sha256'])
    assert grant['newly_sending'] and grant['pin']['credential_ref'] == 'private-key-reference'
    assert not service.begin_attempt(attempt,body['context_sha256'])['newly_sending']
    with runtime.database.connection() as c:
        assert c.execute('SELECT status FROM model_role_unit_attempts WHERE id=%s',(attempt,)).fetchone()['status'] == 'sending'
    with pytest.raises(Conflict,match='read_only'):
        service.execute(owner,job,run,body['request_id'])
    response = json.dumps(['retried']*100)
    service.finish_attempt(attempt,'completed',response)
    service.finish_attempt(attempt,'completed',response)
    with pytest.raises(Conflict,match='terminal_changed'):
        service.finish_attempt(attempt,'unknown')
    assert not service.begin_attempt(attempt,body['context_sha256'])['newly_sending']
    assert service.inspect(owner,job,run)['recovery']['can_continue']
    with runtime.database.connection() as c:
        c.execute('UPDATE jobs SET cancel_requested=true WHERE id=%s',(job,))
    with pytest.raises(Conflict):
        service.prepare_adoption(owner,job,run,body['request_id'])
