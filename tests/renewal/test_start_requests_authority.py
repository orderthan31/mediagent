"""Expected-correct capability and native-ACL tests on disposable PostgreSQL."""
from contextlib import contextmanager
from copy import copy, deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

import pytest
from psycopg import sql
from test_start_requests import db, admin, movie, runtime, saved_case, progress
from test_execution import setup
from test_start_requests_api import actual_client, raw_request
from mideagent_orchestrator.start_requests import StartRequests, MutationGuard, require_guard, Fenced


@pytest.mark.parametrize('kind', ['constructed', 'copied', 'revoked', 'runtime'])
def test_only_live_issued_identity_is_accepted(runtime, admin, movie, kind):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    with service.claim(owner, rid) as guard:
        assert require_guard(guard) is guard
        if kind == 'constructed':
            suspect = MutationGuard(service, guard.root, guard.state, guard.epoch, guard.pid)
        elif kind == 'copied':
            suspect = copy(guard)
        elif kind == 'runtime':
            from video_service.postgres.execution import Execution
            other = Execution(runtime.database, runtime.store)
            with pytest.raises(Fenced):
                require_guard(guard, runtime=other)
            return
        else:
            suspect = guard
        if kind != 'revoked':
            with pytest.raises(Fenced):
                require_guard(suspect)
            return
    with pytest.raises(Fenced):
        require_guard(suspect)


@pytest.mark.parametrize('mismatch', ['operation', 'owner', 'job', 'nonce', 'reuse', 'attributes', 'deepcopy'])
def test_guard_scope_and_lifetime_fences(runtime, admin, movie, mismatch):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    progress(service, owner, rid, 'planned')
    with service.claim(owner, rid) as guard:
        nonce = guard.root['payload']['nonces']['confirm']
        guard.authorize('confirm', owner, job['id'], nonce)
        if mismatch == 'attributes':
            for field, value in [('service', StartRequests(runtime)), ('epoch', guard.epoch + 1),
                                 ('pid', guard.pid + 1), ('root', guard.root), ('state', guard.state)]:
                with pytest.raises((AttributeError, Fenced)):
                    setattr(guard, field, value)
            with runtime.database.connection() as c:
                guard.check(c)
        elif mismatch == 'deepcopy':
            with pytest.raises(Fenced):
                require_guard(deepcopy(guard))
        elif mismatch == 'reuse':
            runtime.confirm(owner, job['id'], guard.state['plan_token'], nonce, _start_guard=guard)
            with pytest.raises(Fenced):
                guard.authorize('confirm', owner, job['id'], nonce)
            with runtime.database.connection() as c, pytest.raises(Fenced):
                guard.check(c)
            with runtime.database.connection() as c, pytest.raises(Fenced):
                guard.finish(c, 'confirmed')
        else:
            args = ('admit' if mismatch == 'operation' else 'confirm',
                    uuid4().hex if mismatch == 'owner' else owner,
                    uuid4().hex if mismatch == 'job' else job['id'],
                    uuid4().hex if mismatch == 'nonce' else nonce)
            with pytest.raises(Fenced):
                guard.authorize(*args)


def test_guard_views_do_not_mutate_authority(runtime, admin, movie):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    state = progress(service, owner, rid, 'planned')
    with service.claim(owner, rid) as guard:
        guard.root['payload']['deadline'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        guard.state['plan_token'] = 'f' * 64
        assert guard.state['plan_token'] == state['plan_token']
        with runtime.database.connection() as c:
            c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
        with runtime.database.connection() as c, pytest.raises(Fenced, match='intent_expired'):
            guard.check(c)
        with pytest.raises(Fenced):
            guard.authorize('admit', owner, job['id'], guard.root['payload']['nonces']['admit'])


@pytest.mark.parametrize('method', ['check', 'finish'])
def test_persisted_deadline_beats_issued_snapshot(runtime, admin, movie, method):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    with service.claim(owner, rid) as guard:
        with runtime.database.connection() as c:
            c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
        with runtime.database.connection() as c, pytest.raises(Fenced, match='intent_expired'):
            if method == 'check':
                guard.check(c)
            else:
                guard.finish(c, 'roles_frozen', roles=[])


@contextmanager
def restricted_database(db):
    """Only synthetic fixture grants; never inspect/use an operating DSN."""
    role = 'start_authority_' + uuid4().hex
    with db.connection() as c:
        schema = c.execute('SELECT current_schema() s').fetchone()['s']
        assert schema.startswith('renewal_test_')
        c.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        c.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        c.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        c.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        c.execute(sql.SQL('REVOKE UPDATE,DELETE ON assets,message_outbox FROM {}').format(sql.Identifier(role)))
        c.execute(sql.SQL('GRANT UPDATE(published_at) ON message_outbox TO {}').format(sql.Identifier(role)))
    class Restricted:
        @contextmanager
        def connection(self):
            with db.connection() as c:
                c.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                yield c
    try:
        restricted = Restricted()
        with restricted.connection() as c:
            assert c.execute("SELECT has_table_privilege(current_user,'assets','SELECT') s,has_table_privilege(current_user,'assets','INSERT') i,has_any_column_privilege(current_user,'assets','UPDATE') u,has_column_privilege(current_user,'message_outbox','published_at','UPDATE') p,has_column_privilege(current_user,'message_outbox','payload','UPDATE') payload").fetchone() == dict(s=True, i=True, u=False, p=True, payload=False)
        yield restricted
    finally:
        with db.connection() as c:
            c.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        with db.connection() as c:
            assert not c.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()


def test_restricted_native_acl_raw_api_worker_admission(runtime, admin, movie, monkeypatch):
    owner = admin[0]['id']
    source, definition, old = setup(runtime, owner, movie)
    original_db = runtime.database
    with restricted_database(original_db) as restricted:
        runtime.database = restricted
        try:
            client, service = actual_client(runtime, admin)
            body = raw_request(client, source, definition)
            with monkeypatch.context() as m:
                def forbidden(*a, **k):
                    pytest.fail('intake performed content I/O')
                m.setattr(runtime.store, 'path', forbidden)
                m.setattr(runtime.store, 'put', forbidden)
                response = client.post('/api/work-entry/create-and-start', json=body)
                assert response.status_code == 202, response.text
                result = response.json()
                assert result['job_id'] is None
                assert client.post('/api/work-entry/create-and-start', json=body).json() == result
                assert client.get('/api/work-entry/start-requests/by-request', params={'request_id': body['request_id']}).json()['id'] == result['id']
                with restricted.connection() as c:
                    assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 1
            state = progress(service, owner, result['id'], 'admitted')
            with restricted.connection() as c:
                assert c.execute('SELECT count(*) n FROM jobs').fetchone()['n'] == 2
                assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 1
                assert c.execute('SELECT count(*) n FROM node_runs').fetchone()['n'] == 0
            assert state['job_id'] != old['id']
        finally:
            runtime.database = original_db


def test_asset_removed_after_intake_blocks_worker(runtime, admin, movie):
    owner = admin[0]['id']
    source, definition, _ = setup(runtime, owner, movie)
    client, service = actual_client(runtime, admin)
    body = raw_request(client, source, definition)
    rid = service.submit_raw(owner, body)['id']
    with runtime.database.connection() as c:
        c.execute("UPDATE assets SET library_removed_at=now(),library_removed_by=%s,library_removal_reason='fixture removal' WHERE id=%s", (owner, source['asset_id']))
    service.process(owner, rid)
    assert service.get(owner, rid)['state'] == 'blocked'
    assert service.get(owner, rid)['job_id'] is None


@pytest.mark.parametrize('late_change', ['expired', 'inactive', 'scope', 'cancel'])
def test_exact_claim_commits_during_actual_unlocked_io(runtime, admin, movie, monkeypatch, late_change):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    state = progress(service, owner, rid, 'confirmed')
    with runtime.database.connection() as c:
        root = service._root(c, owner, rid)
        nonce = root['payload']['nonces']['admit']
        assert service._matching_claim(c, root, state) is None
    entered, release = threading.Event(), threading.Event()
    original = runtime.store.path
    worker = []
    def slow_path(*args, **kwargs):
        if worker and threading.get_ident() == worker[0] and not entered.is_set():
            entered.set()
            assert release.wait(15)
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime.store, 'path', slow_path)
    def process():
        worker.append(threading.get_ident())
        service.process(owner, rid)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(process)
        try:
            assert entered.wait(10)
            # This real public admission must commit while worker I/O is paused.
            runtime.admit(owner, job['id'], state['consent_id'], nonce)
            with runtime.database.connection() as c:
                assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 1
                if late_change == 'expired':
                    c.execute("UPDATE message_outbox SET payload=jsonb_set(payload,'{deadline}',to_jsonb(%s::text)) WHERE id=%s",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), rid))
                elif late_change == 'inactive':
                    c.execute('UPDATE accounts SET active=false WHERE id=%s', (owner,))
                elif late_change == 'scope':
                    c.execute('UPDATE jobs SET revision=revision+1 WHERE id=%s', (job['id'],))
            if late_change == 'cancel':
                assert service.cancel(owner, rid)['state'] == 'admitted'
        finally:
            release.set()
        pending.result(timeout=20)
    with runtime.database.connection() as c:
        final = service._state(c, service._root(c, owner, rid))
        assert final['phase'] == 'admitted', final
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) n FROM node_runs').fetchone()['n'] == 0
    StartRequests(runtime).process(owner, rid)
