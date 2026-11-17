"""Adversarial transaction/restart tests over disposable PostgreSQL."""
from test_start_requests import (db, admin, movie, runtime, saved_case, progress,
    StartRequests, Fenced, REQUESTED, STAGE, TERMINAL, Conflict)
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import threading
from uuid import uuid4

import pytest
from video_service.canonical import digest
from video_service.durable_transport import DurableTransport


@pytest.mark.parametrize('boundary', ['roles_frozen', 'enrolled', 'planned', 'confirmed', 'admitted'])
def test_restart_after_each_commit_and_lost_ack(runtime, admin, movie, monkeypatch, boundary):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    original = service._step
    def lost_reply(g):
        original(g)
        raise OSError('synthetic lost acknowledgement')
    monkeypatch.setattr(service, '_step', lost_reply)
    progress(service, owner, rid, boundary)
    reopened = StartRequests(runtime)
    progress(reopened, owner, rid, 'admitted')
    state = reopened.get(owner, rid)
    assert state['state'] == 'admitted'
    assert runtime.get(owner, job['id'])['runs'] == []
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM message_outbox WHERE published_at IS NOT NULL').fetchone()['n'] == 0


@pytest.mark.parametrize('phase,table', [('planned', 'execution_consents'), ('confirmed', 'execution_claims')])
def test_receipt_failure_rolls_back_domain_mutation(runtime, admin, movie, monkeypatch, phase, table):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    progress(service, owner, rid, phase)
    original = service._append
    def fail(c, root, state, next_phase, **data):
        if next_phase in {'confirmed', 'admitted'}:
            raise RuntimeError('synthetic receipt insert failed')
        return original(c, root, state, next_phase, **data)
    monkeypatch.setattr(service, '_append', fail)
    service.process(owner, rid)
    assert service.get(owner, rid)['state'] == 'uncertain'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] == 0
    assert runtime.get(owner, job['id'])['status'] == 'draft'


def test_two_consumers_and_stale_epoch_cannot_commit(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    other = StartRequests(runtime)
    with service.claim(owner, rid) as stale:
        assert stale is not None
        with pytest.raises(Fenced):
            runtime.confirm(owner, job['id'], 'a' * 64, 'wrong-stage', _start_guard=stale)
        with pytest.raises(Fenced):
            runtime.confirm(owner, job['id'], 'a' * 64, 'invalid-capability', _start_guard={})
        with other.claim(owner, rid) as duplicate:
            assert duplicate is None
    # Session ownership lost, even BEFORE a successor epoch, must fence.
    with runtime.database.connection() as c, pytest.raises(Fenced):
        stale.check(c)
    with other.claim(owner, rid) as successor:
        with runtime.database.connection() as c, pytest.raises(Fenced):
            stale.check(c)
        other._step(successor)
    progress(other, owner, rid, 'admitted')


def test_cancel_during_slow_plan_fences_late_mutation(runtime, admin, movie, monkeypatch):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    progress(service, owner, rid, 'enrolled')
    entered, release = threading.Event(), threading.Event()
    original = runtime.plan
    def slow(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(runtime, 'plan', slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.process, owner, rid)
        assert entered.wait(10)
        assert service.cancel(owner, rid)['state'] == 'cancelled'
        release.set()
        pending.result(timeout=20)
    assert service.get(owner, rid)['state'] == 'cancelled'
    assert runtime.get(owner, job['id'])['status'] == 'draft'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 0


@pytest.mark.parametrize('mutation,expected', [('expired', 'expired'), ('inactive', 'blocked'),
    ('revision', 'blocked'), ('cancel', 'blocked'), ('review_required', 'blocked'), ('generation', 'blocked')])
def test_fresh_authority_fences(runtime, admin, movie, mutation, expected):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    with runtime.database.connection() as c:
        if mutation == 'expired':
            c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
        elif mutation == 'inactive':
            c.execute('UPDATE accounts SET active=false WHERE id=%s', (owner,))
        elif mutation == 'cancel':
            c.execute('UPDATE jobs SET cancel_requested=true WHERE id=%s', (job['id'],))
        elif mutation == 'review_required':
            c.execute("UPDATE jobs SET status='review_required' WHERE id=%s", (job['id'],))
        else:
            c.execute('UPDATE jobs SET ' + mutation + '=' + mutation + '+1 WHERE id=%s', (job['id'],))
    service.process(owner, rid)
    with runtime.database.connection() as c:
        assert service._state(c, service._root(c, owner, rid))['phase'] == expected
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 0


def test_expired_consent_not_renewed_and_admitted_not_relabelled(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    state = progress(service, owner, rid, 'confirmed')
    with runtime.database.connection() as c:
        c.execute("UPDATE execution_consents SET expires_at=now()-interval '1 second' WHERE id=%s", (state['consent_id'],))
    for _ in range(3):
        StartRequests(runtime).process(owner, rid)
    assert service.get(owner, rid)['state'] == 'blocked'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 0


@pytest.mark.parametrize('kind', [REQUESTED, STAGE, TERMINAL, 'internal.start.epoch.v1', 'internal.start.future.v9'])
def test_internal_types_never_reach_any_sender(runtime, admin, movie, kind):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    identity = uuid4().hex
    with runtime.database.connection() as c:
        service._write(c, owner, job['id'], kind, {'private': 'never-send'}, identity)
    def forbidden(*args):
        pytest.fail('internal record reached sender')
    with pytest.raises(Conflict, match='internal_start_record_not_deliverable'):
        DurableTransport(runtime).publish_exact(owner, job['id'], identity, forbidden)
    with runtime.database.connection() as c:
        assert c.execute('SELECT published_at FROM message_outbox WHERE id=%s', (identity,)).fetchone()['published_at'] is None


def test_shutdown_fences_and_restart_resumes(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    with service.claim(owner, rid) as guard:
        service.stopping.set()
        with runtime.database.connection() as c, pytest.raises(Fenced):
            guard.check(c)
    service.tick()
    assert service.get(owner, rid)['state'] == 'queued'
    progress(StartRequests(runtime), owner, rid, 'admitted')
    assert service.cancel(owner, rid)['state'] == 'admitted'
    with runtime.database.connection() as c:
        c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), rid))
    StartRequests(runtime).process(owner, rid)
    assert service.get(owner, rid)['state'] == 'admitted'


def test_authoritative_claim_handoff_to_existing_queue_fake_dispatch(runtime, admin, movie):
    from mideagent_orchestrator.start_queue_progress import advance_start_queue
    from mideagent_orchestrator.start_queue import StartQueue
    service, owner, job, rid = saved_case(runtime, admin, movie)
    progress(service, owner, rid, 'admitted')
    calls = []
    assert job['id'] in StartQueue(runtime).get(owner)['jobs']
    assert advance_start_queue(runtime, owner, lambda o, j: calls.append((o, j)))
    assert calls == [(owner, job['id'])]
    assert runtime.get(owner, job['id'])['runs'] == []
