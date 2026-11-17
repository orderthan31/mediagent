"""Event-blocked real GETs: fresh authority, lock release and no retries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Event, Barrier
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from test_claim_cold_gate import admin, db, movie, prepared, observe, counts
from test_claim_staged_inputs import audio_ready
from mideagent_orchestrator.start_queue import StartQueue
from video_service.canonical import canonical, digest
from video_service.postgres import Conflict


def blocked_get(client, monkeypatch):
    entered, release = Event(), Event()
    original = client.get_object
    seen = []

    def get_object(**kwargs):
        if '/start-queues/' not in kwargs['Key']:
            seen.append(kwargs['Key'])
            if len(seen) == 1:
                entered.set()
                assert release.wait(20), 'test did not release content read'
        return original(**kwargs)

    monkeypatch.setattr(client, 'get_object', get_object)
    return entered, release, seen


def claim_or_conflict(runtime, owner, identity):
    try:
        return runtime.claim_next(owner, identity)
    except Conflict:
        return None


@pytest.mark.parametrize('change', ['cancel', 'generation', 'revision', 'claim', 'queue_pause', 'queue_revision', 'capacity'])
def test_blocked_real_get_all_guards_released_and_drift_rejected(db, admin, movie, tmp_path, monkeypatch, change):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    entered, release, seen = blocked_get(client, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claim_or_conflict, runtime, owner, job['id'])
        try:
            assert entered.wait(20)
            with db.connection() as conn:
                conn.execute("SET LOCAL lock_timeout='500ms'")
                conn.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
                for key in ('start-queue:' + owner, 'agent-pool-capacity:encode'):
                    assert conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked', (key,)).fetchone()['locked']
                changes = {'cancel': 'cancel_requested=true', 'generation': 'generation=generation+1', 'revision': 'revision=revision+1', 'claim': 'active_claim_id=NULL'}
                if change in changes:
                    conn.execute('UPDATE jobs SET ' + changes[change] + ' WHERE id=%s', (job['id'],))
                if change == 'capacity':
                    conn.execute("UPDATE agent_pool_instances SET phase='busy' WHERE role='encode'")
            if change.startswith('queue_'):
                queue = StartQueue(runtime)
                queue.patch(owner, queue.get(owner)['revision'], paused=change == 'queue_pause')
        finally:
            release.set()
        assert future.result(timeout=20) is None
    assert counts(db, job) == (0, 0, 0)
    assert len(seen) == 1, 'drift must discard; no automatic I/O retry'


@pytest.mark.parametrize('change', ['producer_result', 'producer_request', 'review'])
def test_full_ordered_frontier_drift_rejects(db, admin, movie, tmp_path, monkeypatch, change):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    before = counts(db, job)
    entered, release, _ = blocked_get(client, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claim_or_conflict, runtime, owner, job['id'])
        try:
            assert entered.wait(20)
            with db.connection() as conn:
                row = runtime._runs(conn, owner, job['id'])[-1]
                if change == 'producer_result':
                    value = {**row['result'], 'fixture_evidence': 'changed'}
                    conn.execute('UPDATE node_runs SET result=%s WHERE id=%s', (Jsonb(value), row['id']))
                elif change == 'producer_request':
                    value = deepcopy(row['request'])
                    value['options']['fixture_evidence'] = 'changed'
                    conn.execute('UPDATE node_runs SET request=%s,request_sha256=%s WHERE id=%s', (Jsonb(value), digest(value), row['id']))
                else:
                    conn.execute("INSERT INTO review_tasks(owner_id,job_id,node_run_id,id,revision,contract,draft,status) VALUES (%s,%s,%s,%s,1,%s,%s,'draft')", (owner,job['id'],row['id'],uuid4().hex,Jsonb({'version':1}),Jsonb({})))
        finally:
            release.set()
        assert future.result(timeout=20) is None
    assert counts(db, job) == before


def test_snapshot_trigger_stays_enabled(db, admin, movie, tmp_path, monkeypatch):
    from psycopg.errors import CheckViolation
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    entered, release, _ = blocked_get(client, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.claim_next, owner, job['id'])
        try:
            assert entered.wait(20)
            changed = deepcopy(job['snapshot'])
            changed['definition']['name'] = 'forbidden fixture mutation'
            with pytest.raises(CheckViolation, match='snapshot is immutable'):
                with db.connection() as conn:
                    conn.execute('UPDATE jobs SET snapshot=%s,snapshot_sha256=%s WHERE id=%s', (Jsonb(changed),digest(changed),job['id']))
        finally:
            release.set()
        assert future.result(timeout=20)['agent']['id'] == 'encode'
    with db.connection() as conn:
        assert runtime._job(conn,owner,job['id'])['snapshot'] == job['snapshot']


@pytest.mark.parametrize('field', ['source_owner', 'pin', 'snapshot'])
def test_unit_injected_stale_candidate_metadata_not_sql_mutation(db, admin, movie, tmp_path, monkeypatch, field):
    """Explicit targeted unit injection, not an assertion of mutable SQL snapshots."""
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    stage = runtime._stage_claim_candidate

    def stale(candidate):
        frozen = json.loads(candidate)
        before = deepcopy(frozen)
        result = stage(candidate)
        assert frozen == before  # stage cannot retain mutable graph aliases
        # Inject stale staged command binding; final insertion must reject it.
        changed = deepcopy(frozen['job'])
        if field == 'source_owner':
            changed['snapshot']['inputs']['video']['source_owner_id'] = 'f' * 32
        elif field == 'pin':
            changed['snapshot']['model_bindings']['fixture'] = {'revision':2}
        else:
            changed['snapshot']['definition']['name'] = 'stale snapshot'
        return runtime._claim_command_binding(changed, frozen['node'], frozen['inputs'], 'running'), result[1]

    monkeypatch.setattr(runtime, '_stage_claim_candidate', stale)
    with pytest.raises(Conflict, match='staged_command_binding_changed'):
        runtime.claim_next(owner, job['id'])
    assert counts(db, job) == (0, 0, 0)


def test_two_staged_claimers_create_one_command_outbox(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    stage = runtime._stage_claim_candidate
    barrier = Barrier(2)

    def together(candidate):
        value = stage(candidate)
        barrier.wait(timeout=20)
        return value

    monkeypatch.setattr(runtime, '_stage_claim_candidate', together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = list(pool.map(lambda _: runtime.claim_next(owner, job['id']), range(2)))
    assert sum(c is not None for c in commands) == 1
    assert counts(db, job) == (1, 1, 0)


def test_two_started_jobs_same_capacity_never_oversubscribe(db, admin, movie, tmp_path, monkeypatch):
    from test_execution import setup, graph, admit
    runtime, owner, first, client = prepared(db, admin, movie, tmp_path)
    _, _, second = setup(runtime, owner, movie, graph('encode', 'validate_video'))
    admit(runtime, owner, second['id'])
    # Synthetic already-started frontiers; capacity ownership is still real SQL.
    for job in (first, second):
        with db.connection() as conn:
            raw = runtime._job(conn, owner, job['id'], lock=True)
            runtime._insert_run(conn, raw, raw['snapshot']['definition']['nodes'][1], {}, 'skipped')
            conn.execute('INSERT INTO agent_pool_jobs(owner_id,job_id,generation,claim_id) VALUES (%s,%s,%s,%s)', (owner,job['id'],raw['generation'],raw['active_claim_id']))
    observe(db)
    stage = runtime._stage_claim_candidate
    barrier = Barrier(2)
    def together(candidate):
        value = stage(candidate)
        barrier.wait(timeout=20)
        return value
    monkeypatch.setattr(runtime, '_stage_claim_candidate', together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = list(pool.map(lambda j: runtime.claim_next(owner,j['id']), (first,second)))
    assert sum(c is not None for c in commands) == 1
    with db.connection() as conn:
        assert conn.execute("SELECT inflight FROM agent_pool_capacity WHERE role='encode'").fetchone()['inflight'] == 1
        assert conn.execute('SELECT count(*) n FROM message_outbox').fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) n FROM agent_pool_demands WHERE node_run_id IS NOT NULL').fetchone()['n'] == 1
