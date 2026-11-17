"""Durable explicit intake: real disposable PostgreSQL, no provider calls."""
from uuid import uuid4

import pytest
from test_execution import db, admin, movie, runtime, setup
from mideagent_orchestrator.start_requests import StartRequests
from video_service.postgres import Conflict
from mideagent_orchestrator.start_requests import Fenced, REQUESTED, STAGE, TERMINAL
from video_service.canonical import digest
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timezone, timedelta
from psycopg.types.json import Jsonb


def saved_case(runtime, admin, movie):
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie)
    service = StartRequests(runtime)
    receipt = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)
    return service, owner, job, receipt['start_request']['id']


def progress(service, owner, rid, phase):
    for _ in range(12):
        with service.runtime.database.connection() as c:
            state = service._state(c, service._root(c, owner, rid))
        if state['phase'] == phase:
            return state
        assert state['phase'] not in {'blocked', 'uncertain', 'expired', 'cancelled'}, state
        service.process(owner, rid)
    raise AssertionError('stage never reached')


def test_saved_request_replay_and_restart_admits_without_browser(runtime, admin, movie):
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie)
    service = StartRequests(runtime)
    receipt = service.submit_saved(owner, job['id'], job['revision'], 'explicit-start')
    assert receipt['id'] == job['id']
    assert receipt['start_request']['state'] == 'queued'
    rid = receipt['start_request']['id']
    with runtime.database.connection() as c:
        stored = service._root(c, owner, rid)['payload']['nonces']
    assert stored == {stage: digest({'start_request': rid, 'stage': stage})
                      for stage in ('create', 'enroll', 'confirm', 'admit')}
    for _ in range(8):
        StartRequests(runtime).tick()
    result = service.get(owner, rid)
    assert result['state'] == 'admitted'
    assert runtime.get(owner, job['id'])['runs'] == []
    assert service.submit_saved(owner, job['id'], job['revision'], 'explicit-start') == {
        'id': job['id'], 'job_id': job['id'], 'start_request': result['start_request']}
    with pytest.raises(Conflict):
        service.submit_saved(owner, job['id'], job['revision'] + 1, 'explicit-start')
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 1


def test_raw_intake_no_content_io_and_changed_nonce_conflict(runtime, admin, movie, monkeypatch):
    owner = admin[0]['id']
    source, definition, _ = setup(runtime, owner, movie)
    service = StartRequests(runtime)
    body = dict(asset_id=source['asset_id'], definition_id=definition['id'],
                definition_revision=definition['revision'], recovery_enabled=False,
                options={}, request_id='raw-start', token='a' * 64, paid_confirmed=False)
    def forbidden(*a, **k):
        raise AssertionError('intake must not touch content')
    monkeypatch.setattr(runtime.store, 'path', forbidden)
    monkeypatch.setattr(runtime.store, 'put', forbidden)
    receipt = service.submit_raw(owner, body)
    assert receipt['job_id'] is None
    monkeypatch.setattr(service, '_anchors', forbidden)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(lambda _: service.submit_raw(owner, body), range(3))) == [receipt] * 3
    assert receipt == service.submit_raw(owner, body)
    with pytest.raises(Conflict):
        service.submit_raw(owner, {**body, 'paid_confirmed': True})
    assert service.by_nonce(owner, body['request_id'])['id'] == receipt['id']
    assert service.list(owner)['requests'][0]['id'] == receipt['id']
    assert 'token' not in str(service.get(owner, receipt['id']))


def test_cancel_before_worker_never_starts_old_drafts(runtime, admin, movie):
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie)
    service = StartRequests(runtime)
    service.tick()
    assert runtime.get(owner, job['id'])['status'] == 'draft'
    receipt = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)
    rid = receipt['start_request']['id']
    assert service.cancel(owner, rid)['state'] == 'cancelled'
    service.tick()
    assert runtime.get(owner, job['id'])['status'] == 'draft'
