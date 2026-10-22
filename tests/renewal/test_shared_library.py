"""Shared authenticated media, private uploads/control/credentials. Disposable PG only."""
import hashlib
import secrets

from fastapi.testclient import TestClient
from app.renewal import create_app
from video_service.postgres.accounts import Accounts
from test_execution import runtime as runtime, movie as movie
from test_foundation import db as db, admin as admin, login


def member(db, actor):
    password = secrets.token_urlsafe(24)
    return Accounts(db).create('shared-reader', password, actor_id=actor), password


def clients(runtime, admin, db):
    app = create_app(db, allowed_origins=('http://testserver',), secure_cookies=False,
                     content_store=runtime.store, local_execution=True)
    a, b = TestClient(app), TestClient(app)
    other = member(db, admin[0]['id'])
    login(a, admin)
    login(b, other)
    return app, a, b, other


def upload_via_api(client, filename, content):
    from uuid import uuid4

    created=client.post('/api/video-uploads',json={'filename':filename,'size':len(content),'request_id':uuid4().hex})
    assert created.status_code==201
    base='/api/video-uploads/'+created.json()['upload_id']
    assert client.put(base+'/chunks?offset=0',content=content,headers={'Content-Type':'application/octet-stream'}).status_code==200
    complete=client.post(base+'/complete',json={})
    assert complete.status_code==200
    return client.get('/api/videos/'+complete.json()['asset_id']).json()['video']


def test_other_authenticated_user_can_read_original_preview_and_download(runtime, admin, db, movie):
    owner = admin[0]['id']
    source = runtime.ingest(owner, 'shared.mp4', movie)
    app, a, b, other = clients(runtime, admin, db)
    response = b.get('/api/videos')
    assert response.status_code == 200
    assert [v['asset_id'] for v in response.json()['videos']] == [source['asset_id']]
    base = '/api/videos/' + source['asset_id']
    detail = b.get(base)
    assert detail.status_code == 200
    assert detail.json()['video']['uploaded_by'] == owner
    original = b.get(base+'/download')
    assert original.status_code == 200 and original.content == movie
    preview = b.get(base+'/stream')
    assert preview.status_code == 200
    assert hashlib.sha256(preview.content).hexdigest() == source['web_preview']['reference']['sha256']
    ranged = b.get(base+'/stream',headers={'Range':'bytes=0-31'})
    assert ranged.status_code == 206 and ranged.content == preview.content[:32]
    assert b.get(base+'/thumbnail').status_code == 200
    assert b.get('/api/accounts').status_code == 403
    with TestClient(app) as anonymous:
        for path in ['/api/videos',base,base+'/download',base+'/stream',base+'/thumbnail']:
            assert anonymous.get(path).status_code == 401


def test_member_pins_other_upload_and_really_processes_without_original_copy(runtime, admin, db, movie):
    from uuid import uuid4
    from test_execution import graph

    uploader = admin[0]['id']
    app, a, b, other = clients(runtime, admin, db)
    source = upload_via_api(a, 'shared-input.mp4', movie)
    wid = uuid4().hex
    saved = runtime.save_definition(uploader, wid, graph('encode', 'validate_video'))
    actor = other[0]['id']
    selection = {'asset_id':source['asset_id'], 'definition_id':wid,
                 'definition_revision':saved['revision'], 'options':{}}
    preview = b.post('/api/work-entry/preview',json=selection)
    assert preview.status_code == 200
    response = b.post('/api/work-entry/create',json={**selection,'token':preview.json()['token'],
                                                      'request_id':uuid4().hex,'paid_confirmed':False})
    assert response.status_code == 201, response.text
    job = response.json()
    assert job['owner_id'] == actor and job['asset_owner_id'] == uploader
    assert job['snapshot']['asset']['uploaded_by'] == uploader
    reference = job['snapshot']['inputs']['video']
    assert reference['source_owner_id'] == uploader
    assert reference['sha256'] == source['sha256']
    assert runtime.store.path(actor, reference) == runtime.asset_path(uploader, source['asset_id'])
    assert not (runtime.store.owner_root(actor)/reference['storage_key']).exists()
    with db.connection() as connection:
        rows = connection.execute('SELECT owner_id,storage_key,sha256 FROM assets').fetchall()
        assert len(rows)==1 and rows[0]['owner_id']==uploader and rows[0]['sha256']==source['sha256']
    base='/api/renewal/jobs/'+job['id']
    plan=b.get(base+'/plan');assert plan.status_code==200 and plan.json()['ready']
    consent=b.post(base+'/confirm',json={'token':plan.json()['token'],'request_id':uuid4().hex})
    assert consent.status_code==200
    admitted=b.post(base+'/admit',json={'consent_id':consent.json()['id'],'request_id':uuid4().hex})
    assert admitted.status_code==200
    done=b.post(base+'/run',json={})
    assert done.status_code==200 and done.json()['status']=='completed',done.text
    assert all(r['status']=='completed' and r['result']['process_exit_code']==0 for r in done.json()['runs'])
    assert runtime.asset_path(uploader,source['asset_id']).read_bytes()==movie
    shared=a.get(base)
    assert shared.status_code==200 and shared.json()['access']['can_manage'] is False
    output_run=next(r for r in done.json()['runs'] if r['node_type']=='encode')
    output=a.get(base+'/artifacts/'+output_run['id']+'/video')
    assert output.status_code==200 and hashlib.sha256(output.content).hexdigest()==output_run['result']['outputs']['video']['sha256']
    assert a.post(base+'/cancel',json={'revision':done.json()['revision']}).status_code==404
    assert b.get(base+'/inputs/'+output_run['id']+'/video/preview').status_code==200


def test_shared_job_files_do_not_grant_execution_or_credential_access(runtime, admin, db, movie):
    from uuid import uuid4
    from test_execution import setup, admit

    owner=admin[0]['id']
    source,saved,job=setup(runtime,owner,movie)
    admit(runtime,owner,job['id'])
    done=runtime.run_local(owner,job['id'])
    assert done['status']=='completed'
    app,a,b,other=clients(runtime,admin,db)
    base='/api/renewal/jobs/'+job['id']
    detail=b.get(base)
    assert detail.status_code==200,detail.text
    shared=detail.json()
    assert shared['access']['can_manage'] is False and shared['executed_by']==owner
    assert shared['snapshot_redacted'] is True
    assert 'model_bindings' not in shared['snapshot'] and 'engine_bindings' not in shared['snapshot']
    assert all('request' not in r and 'lease_owner' not in r for r in shared['runs'])
    assert b.get('/api/jobs').json()['jobs'][0]['job_id']==job['id']
    assert b.get('/api/jobs/'+job['id']).status_code==200
    run=next(r for r in done['runs'] if r['node_type']=='encode')
    output=run['result']['outputs']['video']
    response=b.get(base+'/artifacts/'+run['id']+'/video?download=true')
    assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==output['sha256']
    preview=b.get(base+'/artifacts/'+run['id']+'/video/preview',headers={'Range':'bytes=0-31'})
    assert preview.status_code==206 and len(preview.content)==32
    original=b.get(base+'/inputs/'+run['id']+'/video')
    assert original.status_code==200 and original.content==movie
    for action,body in [('confirm',{'token':'0'*64,'request_id':uuid4().hex}),
                        ('admit',{'consent_id':uuid4().hex,'request_id':uuid4().hex}),
                        ('run',{}),('cancel',{'revision':done['revision']}),
                        ('recover',{'request_id':uuid4().hex,'acknowledge_duplicate_risk':True})]:
        assert b.post(base+'/'+action,json=body).status_code==404,action
    assert b.get('/api/accounts').status_code==403
    with TestClient(app) as anonymous:
        assert anonymous.get(base).status_code==401
        assert anonymous.get(base+'/artifacts/'+run['id']+'/video').status_code==401
    assert runtime.get(owner,job['id'])['revision']==done['revision']
