"""Actual authenticated API, generic immutable creation and resident lifecycle."""
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from app.renewal import create_app
from app.renewal_routes import Create, SavedStart, Selection
from app.start_request_routes import mount_start_requests
from test_foundation import login
from test_execution import db, admin, movie, runtime, setup
from test_start_requests import progress
from mideagent_orchestrator.start_requests import StartRequests, Fenced
from video_service.postgres import Missing


def actual_client(runtime, admin):
    executors = {role + '_runtime': getattr(runtime, role + '_runtime')
                 for role in ('transcription', 'translation', 'vocalization')
                 if getattr(runtime, role + '_runtime', None) is not None}
    credentials = next((v.credentials for v in executors.values()), None)
    app = create_app(runtime.database, allowed_origins=('http://testserver',),
                     secure_cookies=False, content_store=runtime.store, local_execution=True,
                     credential_store=credentials, **executors)
    # No lifespan here: HTTP-only tests must not dispatch via the separate queue pump.
    client = TestClient(app)
    login(client, admin)
    return client, app.state.start_requests


def raw_request(client, source, definition, options=None):
    selection = dict(asset_id=source['asset_id'], definition_id=definition['id'],
                     definition_revision=definition['revision'], options=options or {}, recovery_enabled=False)
    preview = client.post('/api/work-entry/preview', json=selection)
    assert preview.status_code == 200, preview.text
    return {**selection, 'token': preview.json()['token'], 'request_id': uuid4().hex, 'paid_confirmed': False}


def test_actual_auth_compact_intake_no_io_and_read_only_lookup(runtime, admin, movie, monkeypatch):
    owner = admin[0]['id']
    source, definition, old = setup(runtime, owner, movie)
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition)
    def forbidden(*a, **k):
        pytest.fail('intake/status performed content I/O')
    monkeypatch.setattr(runtime.store, 'path', forbidden)
    monkeypatch.setattr(runtime.store, 'put', forbidden)
    monkeypatch.setattr(runtime.store, 'verify_descriptor', forbidden, raising=False)
    assert client.post('/api/work-entry/create-and-start', json=body, headers={'X-CSRF-Token': ''}).status_code == 403
    response = client.post('/api/work-entry/create-and-start', json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert set(result) == {'id', 'job_id', 'start_request'} and result['job_id'] is None
    assert len(result['id']) == 32
    assert len(response.content) < 220
    assert client.post('/api/work-entry/create-and-start', json=body).json() == result
    assert client.post('/api/work-entry/create-and-start', json={**body, 'paid_confirmed': True}).status_code == 409
    assert client.get('/api/work-entry/start-requests/by-request', params={'request_id': body['request_id']}).json()['id'] == result['id']
    status = client.get('/api/work-entry/start-requests/' + result['id']).json()
    assert status['state'] == 'queued' and status['job_id'] is None
    assert client.get('/api/work-entry/start-requests').json() == {'requests': [status]}
    assert client.get('/api/renewal/jobs/' + old['id'] + '/start-request').json()['start_request'] is None
    saved = client.post('/api/renewal/jobs/' + old['id'] + '/start-request',
                        json={'revision': old['revision'], 'request_id': 'saved-api-start'})
    assert saved.status_code == 202, saved.text
    assert saved.json()['id'] == saved.json()['job_id'] == old['id']
    assert client.get('/api/renewal/jobs/' + old['id'] + '/start-request').json() == saved.json()
    assert client.post('/api/work-entry/create-and-start', json={**body, '_start_guard': {}}).status_code == 422
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 1
    created_user = client.post('/api/accounts', json={'username': 'start-reader', 'password': admin[1]})
    assert created_user.status_code == 201
    client.cookies.clear()
    assert client.get('/api/work-entry/start-requests').status_code == 401
    login(client, ({'username': 'start-reader'}, admin[1]))
    assert client.get('/api/work-entry/start-requests').json() == {'requests': []}
    assert client.get('/api/work-entry/start-requests/' + result['id']).status_code == 404
    assert client.get('/api/work-entry/start-requests/by-request', params={'request_id': body['request_id']}).status_code == 404


@pytest.mark.parametrize('kind', ['video', 'subtitle'])
def test_raw_creation_keeps_normal_validators_and_atomic_bound_receipt(runtime, admin, movie, kind):
    owner = admin[0]['id']
    if kind == 'video':
        source, definition, _ = setup(runtime, owner, movie)
        options = {}
    else:
        from test_subtitle_original_input import text_definition, SRT
        source = runtime.ingest(owner, 'synthetic.srt', SRT.encode())
        definition = runtime.save_definition(owner, uuid4().hex, text_definition())
        options = {'input_language': 'en'}
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition, options)
    result = client.post('/api/work-entry/create-and-start', json=body)
    assert result.status_code == 202, result.text
    rid = result.json()['id']
    state = progress(service, owner, rid, 'created')
    job = runtime.get(owner, state['job_id'])
    assert job['status'] == 'draft'
    assert job['creation_request_id'] != body['request_id']
    if kind == 'subtitle':
        assert job['snapshot']['normal_input_bindings']['transcript']['language'] == 'en'
        assert job['snapshot']['inputs']['transcript']['type'] == 'transcript'
    original_sha = job['snapshot_sha256']
    progress(service, owner, rid, 'admitted')
    assert runtime.get(owner, state['job_id'])['snapshot_sha256'] == original_sha
    assert client.get('/api/renewal/jobs/' + job['id'] + '/start-request').json()['start_request']['id'] == rid


def test_raw_creation_receipt_rollback_and_lost_reply(runtime, admin, movie, monkeypatch):
    owner = admin[0]['id']
    source, definition, _ = setup(runtime, owner, movie)
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition)
    rid = service.submit_raw(owner, body)['id']
    original = service._append
    def fail(c, root, state, phase, **data):
        if phase == 'created':
            raise OSError('receipt failed')
        return original(c, root, state, phase, **data)
    monkeypatch.setattr(service, '_append', fail)
    service.process(owner, rid)
    assert service.get(owner, rid)['state'] == 'uncertain'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 1
    monkeypatch.setattr(service, '_append', original)
    second = service.submit_raw(owner, {**body, 'request_id': uuid4().hex})['id']
    create = service.runtime.create
    def lost(*args, **kwargs):
        create(*args, **kwargs)
        raise OSError('reply lost after commit')
    monkeypatch.setattr(service.runtime, 'create', lost)
    service.process(owner, second)
    assert service.get(owner, second)['job_id']
    progress(service, owner, second, 'admitted')
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 2


def test_raw_cancel_during_validation_no_placeholder_job(runtime, admin, movie, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    owner = admin[0]['id']
    source, definition, _ = setup(runtime, owner, movie)
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition)
    rid = service.submit_raw(owner, body)['id']
    entered, release = threading.Event(), threading.Event()
    actual = service.selection_plan
    def slow(*args):
        entered.set()
        assert release.wait(10)
        return actual(*args)
    monkeypatch.setattr(service, 'selection_plan', slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.process, owner, rid)
        assert entered.wait(10)
        service.cancel(owner, rid)
        release.set()
        future.result(timeout=30)
    assert service.get(owner, rid)['state'] == 'cancelled'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 1


def test_resident_lifespan_continues_without_browser_and_drains(runtime, admin, movie):
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie)
    app = FastAPI()
    mount_start_requests(app, runtime, Depends(lambda: owner), create_model=Create,
        saved_model=SavedStart, selection_model=Selection, selection_plan=None, enabled=True, factory=None)
    service = app.state.start_requests
    rid = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)['start_request']['id']
    async def run():
        async with app.router.lifespan_context(app):
            for _ in range(240):
                if service.get(owner, rid)['state'] == 'admitted':
                    break
                await asyncio.sleep(.05)
            assert service.get(owner, rid)['state'] == 'admitted'
        assert service.stopping.is_set()
    asyncio.run(run())
    assert runtime.get(owner, job['id'])['runs'] == []


def test_enrollment_revision_only_and_frozen_factory_scope(db, admin, movie, tmp_path):
    from test_model_role_orchestration import formal
    runtime, owner, job = formal(db, admin, movie, tmp_path, prepare=False)
    service = StartRequests(runtime, capabilities=('transcription', 'translation'))
    service.factory = SimpleNamespace(model_role_factory=lambda: None,
        model_role_factories={'transcription': lambda: None, 'translation': lambda: None})
    rid = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)['start_request']['id']
    frozen = progress(service, owner, rid, 'roles_frozen')
    assert frozen['roles'] == ['transcription', 'translation']
    progress(service, owner, rid, 'enrolled')
    after = runtime.get(owner, job['id'])
    assert after['snapshot_sha256'] == job['snapshot_sha256']
    assert after['snapshot'] == job['snapshot'] and after['revision'] == job['revision'] + 1
    changed = StartRequests(runtime, capabilities=('transcription',))
    changed.process(owner, rid)
    assert changed.get(owner, rid)['state'] == 'blocked'


@pytest.mark.parametrize('outcome', ['rollback', 'lost_ack'])
def test_role_enrollment_and_receipt_are_atomic(db, admin, movie, tmp_path, monkeypatch, outcome):
    from test_model_role_orchestration import formal
    from mideagent_orchestrator.model_roles import ModelRoleCoordinator
    runtime, owner, job = formal(db, admin, movie, tmp_path, prepare=False)
    service = StartRequests(runtime, capabilities=('transcription',))
    service.factory = SimpleNamespace(model_role_factory=lambda: None)
    rid = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)['start_request']['id']
    progress(service, owner, rid, 'roles_frozen')
    if outcome == 'rollback':
        append = service._append
        def broken(c, root, state, phase, **data):
            if phase == 'enrolled':
                raise OSError('synthetic receipt failure')
            return append(c, root, state, phase, **data)
        monkeypatch.setattr(service, '_append', broken)
    else:
        enroll = ModelRoleCoordinator.enroll_job
        def lost(coordinator, *args, **kwargs):
            enroll(coordinator, *args, **kwargs)
            raise OSError('synthetic acknowledgement loss')
        monkeypatch.setattr(ModelRoleCoordinator, 'enroll_job', lost)
    service.process(owner, rid)
    after = runtime.get(owner, job['id'])
    assert after['snapshot'] == job['snapshot']
    assert after['revision'] == job['revision'] + (outcome == 'lost_ack')
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM model_role_enrollments').fetchone()['n'] == (outcome == 'lost_ack')
        phase = service._state(c, service._root(c, owner, rid))['phase']
    assert phase == ('enrolled' if outcome == 'lost_ack' else 'uncertain')
