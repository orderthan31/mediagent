"""Fresh wall clock, actual session loss and authoritative reconciliation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import time

import psycopg
import pytest
from test_execution import db, admin, movie, runtime, setup
from test_start_requests import saved_case, progress
from test_start_requests_api import actual_client, raw_request
from mideagent_orchestrator.start_requests import StartRequests, Fenced
from video_service.canonical import digest


def test_actual_session_backend_loss_then_takeover_fences_old_worker(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    other = StartRequests(runtime)
    with pytest.raises(psycopg.OperationalError):
        with service.claim(owner, rid) as stale:
            with runtime.database.connection() as c:
                assert c.execute('SELECT pg_terminate_backend(%s) yes', (stale.pid,)).fetchone()['yes']
            with other.claim(owner, rid) as successor:
                assert successor.epoch > stale.epoch
                with runtime.database.connection() as c, pytest.raises(Fenced):
                    stale.check(c)
                other._step(successor)
    progress(other, owner, rid, 'admitted')


def test_creation_deadline_uses_wall_clock_after_slow_io(runtime, admin, movie, monkeypatch):
    owner = admin[0]['id']
    source, definition, _ = setup(runtime, owner, movie)
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition)
    rid = service.submit_raw(owner, body)['id']
    with runtime.database.connection() as c:
        c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
            ((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(), rid))
    actual = runtime.store.path
    def slow(*a, **k):
        time.sleep(1.1)
        return actual(*a, **k)
    monkeypatch.setattr(runtime.store, 'path', slow)
    with service.claim(owner, rid) as guard:
        with pytest.raises(Fenced, match='intent_expired'):
            service.runtime.create(owner, body['asset_id'], body['definition_id'], body['definition_revision'],
                request_id=digest({'start_request': rid, 'stage': 'create'}), _start_guard=guard)
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 1


def test_matching_committed_claim_wins_over_deadline(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    state = progress(service, owner, rid, 'confirmed')
    nonce = digest({'start_request': rid, 'stage': 'admit'})
    # Exercise the unguarded public domain API's authoritative record. The new
    # worker always writes admission+receipt atomically, so cannot create a gap.
    runtime.admit(owner, job['id'], state['consent_id'], nonce)
    with runtime.database.connection() as c:
        c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
    service.process(owner, rid)
    assert service.get(owner, rid)['state'] == 'admitted'
    assert service.cancel(owner, rid)['state'] == 'admitted'


@pytest.mark.parametrize('review', [False, True])
def test_unknown_or_processing_review_never_admits(runtime, admin, movie, review):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    with runtime.database.connection() as c:
        raw = runtime._job(c, owner, job['id'], lock=True)
        row, _ = runtime._insert_run(c, raw, raw['snapshot']['definition']['nodes'][0], {}, 'skipped')
        if review:
            c.execute("INSERT INTO job_processing_cases(id,owner_id,job_id,node_run_id,cause,evidence_sha256) VALUES (%s,%s,%s,%s,'dispatch_unknown',%s)",
                (uuid4().hex, owner, job['id'], row['id'], 'a' * 64))
    service.process(owner, rid)
    assert service.get(owner, rid)['state'] == 'blocked'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 0


def test_fair_scan_skips_locked_old_request(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    other = service.submit_saved(owner, job['id'], job['revision'], uuid4().hex)['start_request']['id']
    first, second = sorted([rid, other])
    with service.claim(owner, first):
        scanner = StartRequests(runtime)
        scanner.tick(limit=1)
        scanner.tick(limit=1)
        assert scanner.get(owner, second)['state'] == 'preparing'
    assert service.get(owner, first)['state'] == 'queued'
