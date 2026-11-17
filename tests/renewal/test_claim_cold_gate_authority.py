"""Cold gate authority and progress, using real isolated PG and S3 adapter."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from test_claim_cold_gate import admin, db, movie, prepared, observe, demands, counts
from test_execution import graph
from mideagent_orchestrator.start_queue import StartQueue


def independent(kind='validate_video'):
    definition = graph('encode', kind)
    definition['edges'][1]['source'] = {'node': '$input', 'port': 'video'}
    return definition


@pytest.mark.parametrize('kind', ['validate_video', 'review', 'select'])
def test_later_independent_work_not_hidden_by_first_cold_role(db, admin, movie, tmp_path, kind):
    definition = independent(kind)
    if kind == 'select':
        definition['nodes'][1]['options'] = {'data_type': 'video', 'selection': 'a'}
        definition['edges'][1]['target']['port'] = 'value'
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, definition)
    command = runtime.claim_next(owner, job['id'])
    assert client.content_reads
    with db.connection() as conn:
        runs = runtime._runs(conn, owner, job['id'])
    assert len(runs) == 1 and runs[0]['node_id'] == 'n1'
    assert runs[0]['status'] == {'review': 'review_required', 'select': 'completed'}.get(kind, 'running')
    assert (command is not None) == (kind == 'validate_video')
    assert len(demands(db, job)) == 1 and demands(db, job)[0]['node_run_id'] is None


@pytest.mark.parametrize('parent_status,child_status', [('failed', 'blocked'), ('skipped', 'skipped')])
def test_later_terminal_metadata_progress_not_hidden(db, admin, movie, tmp_path, parent_status, child_status):
    definition = independent('encode')
    definition['nodes'].append({**definition['nodes'][1], 'id': 'n2'})
    definition['edges'].append({'id': 'e2', 'source': {'node': 'n1', 'port': 'video'}, 'target': {'node': 'n2', 'port': 'video'}})
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, definition)
    with db.connection() as conn:
        raw = runtime._job(conn, owner, job['id'], lock=True)
        # Fixture metadata only: no command is published/executed.
        runtime._insert_run(conn, raw, raw['snapshot']['definition']['nodes'][1], {}, parent_status)
        from mideagent_orchestrator.agent_pool import AgentPool
        conn.execute('INSERT INTO agent_pool_jobs(owner_id,job_id,generation,claim_id) VALUES (%s,%s,%s,%s)', (owner, job['id'], raw['generation'], raw['active_claim_id']))
    assert runtime.claim_next(owner, job['id']) is None
    with db.connection() as conn:
        runs = runtime._runs(conn, owner, job['id'])
    assert {r['node_id']: r['status'] for r in runs} == {'n1': parent_status, 'n2': child_status}
    assert client.content_reads and counts(db, job) == (2, 0, 0)
    assert len(demands(db, job)) == 1


@pytest.mark.parametrize('fence', ['cancel', 'missing_claim', 'status', 'paused', 'membership'])
def test_ineligible_jobs_create_no_demand(db, admin, movie, tmp_path, fence):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    if fence == 'paused':
        queue = StartQueue(runtime)
        queue.patch(owner, queue.get(owner)['revision'], paused=True)
    elif fence == 'membership':
        from video_service.start_queue_policy import encode_policy
        queue = StartQueue(runtime)
        policy, token = queue.load(owner)
        runtime.store.write_start_queue(owner, encode_policy({**policy, 'members': [], 'order': []}), token)
    else:
        assignments = {'cancel': 'cancel_requested=true', 'missing_claim': 'active_claim_id=NULL', 'status': "status='review_required'"}
        with db.connection() as conn:
            conn.execute('UPDATE jobs SET ' + assignments[fence] + ' WHERE id=%s', (job['id'],))
    assert runtime.claim_next(owner, job['id']) is None
    assert not demands(db, job) and counts(db, job) == (0, 0, 0)


@pytest.mark.parametrize('fence', ['active_cap', 'processing_review', 'unenrolled'])
def test_started_job_fences_and_historical_no_adoption(db, admin, movie, tmp_path, fence):
    definition = independent('validate_video')
    definition['nodes'].append({**definition['nodes'][1], 'id': 'n2'})
    definition['edges'].append({'id': 'e2', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'n2', 'port': 'video'}})
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, definition)
    with db.connection() as conn:
        raw = runtime._job(conn, owner, job['id'], lock=True)
        nodes = raw['snapshot']['definition']['nodes']
        row, _ = runtime._insert_run(conn, raw, nodes[1], {}, 'running' if fence == 'active_cap' else 'skipped')
        if fence == 'active_cap':
            runtime._insert_run(conn, raw, nodes[2], {}, 'running')
        if fence == 'processing_review':
            conn.execute("INSERT INTO job_processing_cases(id,owner_id,job_id,node_run_id,cause,evidence_sha256) VALUES (%s,%s,%s,%s,'dispatch_unknown',%s)", (uuid4().hex, owner, job['id'], row['id'], 'a' * 64))
    before = counts(db, job)
    command = runtime.claim_next(owner, job['id'])
    assert not demands(db, job)
    with db.connection() as conn:
        assert not conn.execute('SELECT 1 FROM agent_pool_jobs WHERE job_id=%s', (job['id'],)).fetchone()
    if fence == 'unenrolled':
        assert command['agent']['id'] == 'encode' and client.content_reads
        assert counts(db, job) == (before[0] + 1, 1, 0)
    else:
        assert command is None and counts(db, job) == before


def test_all_independent_cold_roles_are_prepared_before_shortcut(db, admin, movie, tmp_path):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, independent())
    with db.connection() as conn:
        conn.execute("INSERT INTO agent_pool_roles SELECT 'validate_video',max_instances,memory_bytes,idle_seconds,template_sha256,enabled FROM agent_pool_roles WHERE role='encode'")
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads and counts(db, job) == (0, 0, 0)
    assert {d['role'] for d in demands(db, job)} == {'encode', 'validate_video'}
    assert all(d['node_run_id'] is None for d in demands(db, job))


def test_earlier_ready_command_does_not_prepare_unreached_later_role(db, admin, movie, tmp_path):
    definition = independent()
    definition['nodes'].reverse()
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, definition)
    command = runtime.claim_next(owner, job['id'])
    assert command['agent']['id'] == 'validate_video' and client.content_reads
    assert not demands(db, job) and counts(db, job) == (1, 1, 0)


def test_concurrent_cold_then_ready_exactly_one_command(db, admin, movie, tmp_path):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: runtime.claim_next(owner, job['id']), range(2))) == [None, None]
    assert not client.content_reads and len(demands(db, job)) == 1
    assert counts(db, job) == (0, 0, 0)
    observe(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = list(pool.map(lambda _: runtime.claim_next(owner, job['id']), range(2)))
    assert len([c for c in commands if c is not None]) == 1
    assert counts(db, job) == (1, 1, 0)


@pytest.mark.parametrize('change', ['cancel', 'capacity', 'paused', 'generation'])
def test_fresh_final_claim_rechecks_after_unlocked_preflight(db, admin, movie, tmp_path, monkeypatch, change):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    preflight = runtime._stage_claim_candidate
    observed = []

    def during_preflight(*args, **kwargs):
        with db.connection() as conn:
            # All early locks must have been released, not merely savepointed.
            conn.execute("SET LOCAL lock_timeout='500ms'")
            assert conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked", ('start-queue:' + owner,)).fetchone()['locked']
            conn.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
            assert conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('agent-pool-capacity:encode',0)) locked").fetchone()['locked']
            if change == 'cancel':
                conn.execute('UPDATE jobs SET cancel_requested=true WHERE id=%s', (job['id'],))
            elif change == 'capacity':
                conn.execute("UPDATE agent_pool_instances SET phase='busy' WHERE role='encode'")
            elif change == 'generation':
                conn.execute('UPDATE jobs SET generation=generation+1 WHERE id=%s', (job['id'],))
        if change == 'paused':
            queue = StartQueue(runtime)
            queue.patch(owner, queue.get(owner)['revision'], paused=True)
        observed.append(True)
        return preflight(*args, **kwargs)

    monkeypatch.setattr(runtime, '_stage_claim_candidate', during_preflight)
    assert runtime.claim_next(owner, job['id']) is None
    assert observed == [True] and counts(db, job) == (0, 0, 0)
    assert len(demands(db, job)) == 1 and demands(db, job)[0]['node_run_id'] is None
