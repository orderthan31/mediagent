"""Actual authenticated queue routes over synthetic policy/DB; ASGI only, no listener."""
import ast
import asyncio
import hmac
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from test_start_queue import FakeDatabase, OWNER, enroll
from video_service.content_store import ContentStore

ROOT = Path(__file__).resolve().parents[2]


def actual_app(runtime):
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from video_service.admission_policy import AdmissionPolicy
    app = FastAPI()
    tree = ast.parse((ROOT / 'apps/api/app/renewal.py').read_text(encoding='utf8'))
    nodes = [n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in {'session','request_boundary','JsonBodyLimit'}]
    ns = dict(app=app, Request=Request, HTTPException=HTTPException, JSONResponse=JSONResponse,
              accounts=SimpleNamespace(session=lambda token:{'user':{'id':OWNER,'role':'user'},'csrf_token':'csrf'} if token=='valid' else None),
              cookie='unit_session',hmac=hmac,origins={'https://queue.invalid'},content_store=runtime.store,
              policy=AdmissionPolicy(),re=re)
    for node in nodes:
        exec(compile(ast.Module(body=[node],type_ignores=[]),'renewal.py','exec'),ns)
    app.add_middleware(ns['JsonBodyLimit'],uploads=True)
    path = ROOT / 'apps/api/app/start_queue_routes.py'
    spec = importlib.util.spec_from_file_location('queue_route_unit',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dispatches=[]
    module.mount_start_queue(app,runtime,Depends(ns['session']),
                             dispatch_exact=lambda owner,id:dispatches.append((owner,id)),enabled=True)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=422)
    return app,dispatches


def call(app, method='GET', body=None, *, csrf='csrf', cookie='valid',origin='https://queue.invalid'):
    async def invoke():
        output=[]
        pending=[dict(type='http.request',body=json.dumps(body).encode() if body is not None else b'',more_body=False)]
        async def receive():
            if pending:return pending.pop()
            await asyncio.Event().wait()
        async def send(message):output.append(message)
        await app(dict(type='http',http_version='1.1',method=method,scheme='https',path='/api/queue',raw_path=b'/api/queue',query_string=b'',
                       headers=[(b'host',b'queue.invalid'),(b'origin',origin.encode()),(b'content-type',b'application/json'),
                                (b'cookie',('unit_session='+cookie).encode()),(b'x-csrf-token',csrf.encode())],
                       client=('unit',1),server=('queue.invalid',443),root_path=''),receive,send)
        return output[0]['status'],json.loads(b''.join(row.get('body',b'') for row in output))
    return asyncio.run(invoke())


@pytest.fixture
def case(tmp_path):
    from mideagent_orchestrator.start_queue import StartQueue
    db=FakeDatabase()
    runtime=SimpleNamespace(database=db,store=ContentStore(tmp_path),_queue_start_ready_in=lambda *args:True)
    return runtime,StartQueue(runtime),db


def test_real_route_auth_csrf_origin_revision_null_partial_foreign_started(case):
    runtime,queue,db=case
    a,b=[db.add(i) for i in (40,41)]
    for job in (a,b):enroll(queue,db,job)
    app,dispatches=actual_app(runtime)
    assert call(app,cookie='absent')[0]==401
    assert call(app,'PATCH',dict(revision=2,paused=True),csrf='bad')[0]==403
    assert call(app,'PATCH',dict(revision=2,paused=True),origin='https://other.invalid')[0]==403
    before=len(db.calls)
    status,body=call(app)
    assert status==200 and body['jobs']==[a['id'],b['id']] and dispatches==[]
    assert all('UPDATE ' not in str(x) and 'pg_advisory' not in str(x) for x in db.calls[before:])
    status,state=call(app,'PATCH',dict(revision=2,paused=True,order=[b['id']]))
    assert status==200 and state['jobs']==[b['id'],a['id']] and dispatches==[]
    assert call(app,'PATCH',dict(revision=2,paused=False))[0]==409
    assert call(app,'PATCH',dict(revision=3,order=['f'*32]))[0]==404
    status,state=call(app,'PATCH',dict(revision=3,paused=None,order=None))
    assert status==200 and state['paused'] and state['order']==[b['id']]
    status,state=call(app,'PATCH',dict(revision=4,paused=False,order=[]))
    assert status==200 and dispatches==[(OWNER,a['id']),(OWNER,b['id'])]
    db.jobs[a['id']]['started']=True
    assert call(app,'PATCH',dict(revision=5,order=[a['id']]))[0]==409
    for change in [{'actor':OWNER},{'storage_key':'private'},{'order':['0'*32]*1001}]:
        assert call(app,'PATCH',dict(revision=5,**change))[0]==422


def test_read_failure_is_not_empty_and_no_lost_patch_retry(case,monkeypatch):
    runtime,queue,db=case
    app,dispatches=actual_app(runtime)
    reads=runtime.store.read_start_queue
    def unavailable(owner):raise OSError('PRIVATE synthetic root')
    monkeypatch.setattr(runtime.store,'read_start_queue',unavailable)
    status,body=call(app)
    assert status==503 and 'jobs' not in body and 'PRIVATE' not in json.dumps(body)
    monkeypatch.setattr(runtime.store,'read_start_queue',reads)
    writes=runtime.store.write_start_queue
    count=[]
    def lost(owner,raw,token):
        count.append(owner);writes(owner,raw,token);raise OSError('response lost')
    monkeypatch.setattr(runtime.store,'write_start_queue',lost)
    assert call(app,'PATCH',dict(revision=0,paused=True))[0]==503
    assert len(count)==1 and call(app)[1]['paused'] is True


def test_existing_api_lifecycle_wakes_pending_capacity_without_resident_dispatcher(case):
    runtime,queue,db=case
    value=db.add(40)
    enroll(queue,db,value)
    app,dispatches=actual_app(runtime)
    async def check():
        async with app.router.lifespan_context(app):
            for _ in range(50):
                if dispatches:break
                await asyncio.sleep(0.01)
            assert dispatches==[(OWNER,value['id'])]
    asyncio.run(check())


def test_maintenance_default_deny_unchanged_and_mount_connected():
    from video_service.admission_policy import AdmissionPolicy
    policy=AdmissionPolicy('maintenance','encode','a'*32)
    assert not policy.permits('GET','/api/queue') and not policy.permits('PATCH','/api/queue')
    tree=ast.parse((ROOT/'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    assert any(n.func.id=='mount_start_queue' for n in calls)


def test_start_and_direct_run_share_queue_error_status_boundary(case):
    from fastapi import HTTPException
    from video_service.object_store import ObjectStoreError
    runtime,queue,db=case
    app,_=actual_app(runtime)
    module=next(route.endpoint.__globals__ for route in app.routes if getattr(route,'path','')=='/api/queue')
    def denied():raise ObjectStoreError('PRIVATE remote body',status=403,code='AccessDenied')
    with pytest.raises(HTTPException) as error:
        module['queue_request'](denied)
    assert error.value.status_code==403 and 'AccessDenied' in error.value.detail and 'PRIVATE' not in error.value.detail
    tree=ast.parse((ROOT/'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    mount=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='mount_runtime')
    admit=next(n for n in mount.body if isinstance(n,ast.FunctionDef) and n.name=='admit')
    run=next(n for n in mount.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='queue_request' for n in ast.walk(admit))
    assert sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='queue_request' for n in ast.walk(run))==2
