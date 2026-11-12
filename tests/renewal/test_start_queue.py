"""New-start queue unit contracts over real domain code and a labelled fake DB.

No PostgreSQL, schemas, DSN, network, jobs or provider executions are created.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'packages/shared'), str(ROOT / 'apps/orchestrator')]
from video_service.canonical import digest
from video_service.content_store import ContentStore
from video_service.start_queue_policy import claim_digest, initial_policy, encode_policy, QueueConflict, QueueMissing

OWNER, FOREIGN, CONSENT = 'a' * 32, 'b' * 32, 'c' * 32


class FakeDatabase:
    """SQL result adapter only; eligibility/order decisions live in StartQueue."""
    def __init__(self):
        self.jobs, self.claims, self.calls = {}, {}, []

    @contextmanager
    def connection(self):
        self.calls.append('BEGIN')
        try:
            yield self
        finally:
            self.calls.append('END')

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if 'pg_advisory_xact_lock' in sql:
            rows = []
        elif 'JOIN execution_claims' in sql:
            owner, ids = params
            rows = [dict(job, **self.claims[job['active_claim_id']]) for id, job in self.jobs.items()
                    if id in ids and job['owner_id'] == owner and job['active_claim_id'] in self.claims]
        elif 'FROM execution_claims' in sql:
            owner, job_id, claim = params
            row = self.claims.get(claim)
            rows = [row] if row and self.jobs.get(job_id, {}).get('owner_id') == owner else []
        else:
            raise AssertionError('Unexpected synthetic SQL: ' + sql)
        return SimpleNamespace(fetchall=lambda: deepcopy(rows), fetchone=lambda: deepcopy(rows[0]) if rows else None)

    def add(self, number, *, owner=OWNER, started=False, new=True, status='waiting', generation=1):
        id, claim = f'{number:032x}', f'{number + 1000:032x}'
        row = dict(id=id, owner_id=owner, generation=generation, active_claim_id=claim,
                   status=status, cancel_requested=False, started=started, active=False,
                   deliverable=False, uncertain=False,
                   ticket_number=number, filename=f'원본 {number}.mp4', workflow_name='작업',
                   created_at='2026-11-12T00:00:00+00:00')
        self.jobs[id] = row
        self.claims[claim] = dict(claim_id=claim, claim_generation=generation, consent_id=CONSENT,
                                 request_sha256=claim_digest(id, CONSENT) if new else digest(dict(job=id, consent=CONSENT)))
        return row


@pytest.fixture
def case(tmp_path):
    from mideagent_orchestrator.start_queue import StartQueue
    db = FakeDatabase()
    runtime = SimpleNamespace(database=db, store=ContentStore(tmp_path),
                              _queue_start_ready_in=lambda db, job: True)
    return StartQueue(runtime), db, runtime


def enroll(queue, db, job):
    with db.connection():
        queue.lock_in(db, job['owner_id'])
        queue.enroll_in(db, job, job['active_claim_id'])


def test_new_members_only_shared_jobs_not_silently_global_controls(case):
    queue, db, runtime = case
    old = db.add(32, new=False)
    draft = db.add(33, status='draft')
    foreign = db.add(34, owner=FOREIGN)
    assert queue.get(OWNER)['jobs'] == []
    assert queue.allowed_in(db, old)
    job = db.add(40)
    enroll(queue, db, job)
    state = queue.get(OWNER)
    assert state['jobs'] == [job['id']] and state['revision'] == 1
    assert state['details'][0]['original_filename'] == '원본 40.mp4'
    assert queue.get(FOREIGN)['revision'] == 0
    for id in (old['id'], draft['id'], foreign['id']):
        with pytest.raises(QueueMissing):
            queue.patch(OWNER, state['revision'], order=[id])
    public = str(state)
    assert job['active_claim_id'] not in public and CONSENT not in public


def test_pause_order_partial_empty_null_revision_and_started_guards(case):
    queue, db, runtime = case
    a, b, c = [db.add(i) for i in (40, 41, 42)]
    for job in (a, b, c):
        enroll(queue, db, job)
    state = queue.patch(OWNER, 3, paused=True, order=[c['id']])
    assert state['jobs'] == [c['id'], a['id'], b['id']]
    assert not queue.allowed_in(db, c)
    assert queue.get(OWNER)['paused'] is True
    with pytest.raises(QueueConflict):
        queue.patch(OWNER, 3, paused=False)
    same = queue.patch(OWNER, state['revision'], paused=None, order=None)
    assert same['paused'] and same['order'] == [c['id']]
    state = queue.patch(OWNER, same['revision'], paused=False, order=[])
    assert state['jobs'] == [a['id'], b['id'], c['id']]
    assert queue.allowed_in(db, a) and not queue.allowed_in(db, b)
    db.jobs[a['id']]['started'] = True
    assert queue.allowed_in(db, b)  # Start order, not completion FIFO.
    with pytest.raises(QueueConflict):
        queue.patch(OWNER, state['revision'], order=[a['id']])


def test_orphan_generation_and_missing_enrollment_fail_closed_without_old_adoption(case):
    queue, db, runtime = case
    a, b = db.add(40), db.add(41)
    enroll(queue, db, a)
    enroll(queue, db, b)
    db.jobs[a['id']]['generation'] += 1
    assert queue.get(OWNER)['jobs'] == [b['id']]
    assert queue.allowed_in(db, b)
    assert not queue.allowed_in(db, a)
    missing = db.add(42)
    assert not queue.allowed_in(db, missing)
    # A remote write before the DB admission commit is only an ignored orphan.
    del db.claims[b['active_claim_id']]
    assert queue.get(OWNER)['jobs'] == []
    assert db.jobs[a['id']]['status'] == 'waiting'


def test_available_slot_parallelism_skips_unready_predecessor_without_ignoring_order(case):
    queue, db, runtime = case
    a, b = db.add(40), db.add(41)
    enroll(queue, db, a)
    enroll(queue, db, b)
    runtime._queue_start_ready_in = lambda conn, job: job['id'] != a['id']
    assert queue.allowed_in(db, b)
    assert queue.allowed_in(db, a)  # Native claim may prepare demand, never bypasses capacity.
    runtime._queue_start_ready_in = lambda conn, job: True
    assert not queue.allowed_in(db, b)


def test_patch_serializes_queue_before_job_reads_and_storage_failure_is_not_empty(case, monkeypatch):
    queue, db, runtime = case
    job = db.add(40)
    enroll(queue, db, job)
    db.calls.clear()
    queue.patch(OWNER, 1, paused=True)
    queries = [x[0] for x in db.calls if isinstance(x, tuple)]
    assert 'pg_advisory_xact_lock' in queries[0]
    def unavailable(owner):
        raise OSError('synthetic unavailable')
    monkeypatch.setattr(runtime.store, 'read_start_queue', unavailable)
    with pytest.raises(OSError):
        queue.get(OWNER)
