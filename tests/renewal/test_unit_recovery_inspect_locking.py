"""Offline lock model: real recovery code, synthetic WAV, no PostgreSQL/provider.

The fake only models FOR UPDATE ownership until transaction exit, not PostgreSQL
isolation or production latency. Events keep the slow source read deterministic.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from video_service.canonical import digest
from video_service.postgres import Conflict
from video_service.postgres.unit_recovery import RoleUnitRecovery
from video_service.role_policy import model_binding
from test_unit_recovery_core import fixture, call


class Rows:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, database):
        self.database = database
        self.locked = False

    def execute(self, sql, params=()):
        self.database.queries.append(sql)
        assert sql.startswith('SELECT '), 'inspection must remain read-only'
        if 'FOR UPDATE' in sql and not self.locked:
            assert self.database.lock.acquire(timeout=3), 'fake lock acquisition timed out'
            self.locked = True
        if 'to_regclass' in sql:
            return Rows([{'name': 'model_role_unit_recoveries'}])
        table = sql.split(' FROM ')[1].split()[0]
        return Rows(self.database.rows[table])


class Database:
    def __init__(self, rows):
        self.rows, self.queries, self.lock = rows, [], Lock()

    @contextmanager
    def connection(self):
        db = Connection(self)
        try:
            yield db
        finally:
            if db.locked:
                self.lock.release()


class Store:
    def __init__(self, raw):
        self.raw, self.reads = raw, 0
        self.entered, self.release = Event(), Event()
        self.release.set()
        self.after_read = lambda: None

    def read(self, owner, ref, *, limit):
        self.reads += 1
        self.entered.set()
        assert self.release.wait(3), 'test did not release slow source read'
        self.after_read()
        return self.raw


def runtime_fixture():
    task, raw, units = fixture()
    pin = dict(model_id='b'*32, revision=1, credential_ref='private')
    task['models'] = [model_binding(pin)]
    job_id, run_id = 'c'*32, 'd'*32
    ref = dict(task['audio'], storage_key='synthetic.wav', type='audio')
    command = dict(run_id=job_id, attempt_id=run_id, generation=1, inputs={'audio': ref})
    envelope = dict(role='transcription', task=task)
    rows = dict(
        jobs=[dict(id=job_id, owner_id='owner', revision=1, generation=1,
                   active_claim_id='claim', status='waiting', cancel_requested=False,
                   snapshot={}, snapshot_sha256=digest({}))],
        node_runs=[dict(id=run_id, request=command, request_sha256=digest(command),
                        generation=1, claim_id='claim', status='running', result=None)],
        model_role_tasks=[dict(task_id=task['task_id'], generation=1, phase='held',
                               request_sha256=digest(command), envelope=envelope,
                               envelope_sha256=digest(envelope), frozen_candidates=[pin],
                               result_sha256=None)],
        model_role_tool_calls=[call(task, units, 0), call(task, units, 1, 'failed')],
        model_role_unit_recoveries=[], model_role_result_deliveries=[],
        model_role_unit_attempts=[])
    database = Database(rows)
    runtime = SimpleNamespace(database=database, store=Store(raw))
    runtime._shared_job = lambda db, identity: db.execute(
        'SELECT * FROM jobs WHERE id=%s FOR UPDATE', (identity,)).fetchone()
    return runtime, job_id, run_id


@pytest.mark.parametrize('inspect', [True, False])
def test_slow_source_read_releases_get_locks_but_not_mutation_locks(inspect):
    runtime, job, run = runtime_fixture()
    runtime.store.release.clear()
    service = RoleUnitRecovery(runtime)

    def request():
        if inspect:
            return service.inspect('owner', job, run)
        with runtime.database.connection() as db:
            return service._facts(db, 'owner', job, run, manage=True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(request)
        try:
            assert runtime.store.entered.wait(2)
            acquired = runtime.database.lock.acquire(timeout=0.1)
            if acquired:
                runtime.database.lock.release()
            assert acquired is inspect
        finally:
            runtime.store.release.set()
        future.result(timeout=3)


def test_each_get_revalidates_bytes_and_fresh_calls_across_instances():
    runtime, job, run = runtime_fixture()
    first = RoleUnitRecovery(runtime).inspect('owner', job, run)
    runtime.database.rows['model_role_tool_calls'][1].update(status='unknown')
    second = RoleUnitRecovery(runtime).inspect('reader', job, run)
    assert second['blocked_reason'] == 'unit_recovery_evidence_unresolved'
    assert second['context_sha256'] != first['context_sha256']
    assert not second['access']['can_manage']
    assert runtime.store.reads == 2
    runtime.store.raw = b'corrupt'
    with pytest.raises(Conflict, match='source_changed'):
        RoleUnitRecovery(runtime).inspect('owner', job, run)


@pytest.mark.parametrize('change', ['calls', 'revision', 'source', 'model'])
def test_change_during_slow_read_cannot_reuse_manifest(change):
    runtime, job, run = runtime_fixture()

    def mutate():
        rows = runtime.database.rows
        if change == 'calls':
            rows['model_role_tool_calls'][1]['status'] = 'unknown'
        elif change == 'revision':
            rows['jobs'][0]['revision'] += 1
        elif change == 'source':
            row = rows['node_runs'][0]
            row['request']['inputs']['audio']['storage_key'] = 'other.wav'
            row['request_sha256'] = digest(row['request'])
            rows['model_role_tasks'][0]['request_sha256'] = row['request_sha256']
        else:
            row = rows['model_role_tasks'][0]
            row['frozen_candidates'][0]['revision'] += 1
            row['envelope']['task']['models'] = [model_binding(row['frozen_candidates'][0])]
            row['envelope_sha256'] = digest(row['envelope'])

    runtime.store.after_read = mutate
    with pytest.raises(Conflict, match='changed'):
        RoleUnitRecovery(runtime).inspect('owner', job, run)


def test_manifest_construction_also_runs_outside_get_locks(monkeypatch):
    from video_service import unit_recovery
    runtime, job, run = runtime_fixture()
    original = unit_recovery.build_manifest
    calls = []

    def build(*args):
        assert runtime.database.lock.acquire(blocking=False)
        runtime.database.lock.release()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(unit_recovery, 'build_manifest', build)
    for _ in range(6):
        RoleUnitRecovery(runtime).inspect('owner', job, run)
    assert len(calls) == runtime.store.reads == 6


@pytest.mark.parametrize('change', ['cancel', 'result', 'delivery'])
def test_final_view_observes_fresh_blockers(change):
    runtime, job, run = runtime_fixture()

    def mutate():
        rows = runtime.database.rows
        if change == 'cancel':
            rows['jobs'][0]['cancel_requested'] = True
        elif change == 'result':
            rows['node_runs'][0]['result'] = {}
        else:
            rows['model_role_result_deliveries'] = [dict(
                packet={}, packet_sha256=digest({}), state='pending', revision=1)]

    runtime.store.after_read = mutate
    if change == 'delivery':
        with pytest.raises(Conflict, match='context_changed'):
            RoleUnitRecovery(runtime).inspect('owner', job, run)
    else:
        view = RoleUnitRecovery(runtime).inspect('owner', job, run)
        assert view['blocked_reason'] == 'unit_recovery_root_not_held'


def test_new_recovery_and_completed_attempt_are_read_fresh_and_reverified():
    runtime, job, run = runtime_fixture()
    service = RoleUnitRecovery(runtime)
    with runtime.database.connection() as db:
        facts = service._facts(db, 'owner', job, run)
    context, manifest = facts[4:6]
    recovery = dict(id='e'*32, owner_id='owner', job_id=job, run_id=run,
                    task_id=context['task_id'], revision=1, request_id='new', status='approved',
                    context=context, context_sha256=digest(context), manifest=manifest,
                    decisions=[dict(unit_index=1, action='retry', candidate_index=0)],
                    reused_attempts=[], additional_call_limit=1, approve_calls=True)
    terminal = dict(status='completed', response=[dict(start=0, end=0.5, text='retry')], error_code=None)
    attempt = dict(id='f'*32, recovery_id=recovery['id'], unit_index=1, candidate_index=0,
                   input_sha256=manifest['units'][1]['input_sha256'], **terminal,
                   terminal_sha256=digest(terminal))

    def complete():
        runtime.database.rows['model_role_unit_recoveries'] = [recovery]
        runtime.database.rows['model_role_unit_attempts'] = [attempt]

    runtime.store.after_read = complete
    view = service.inspect('owner', job, run)
    assert view['recovery']['request_id'] == 'new'
    assert view['units'][1]['status'] == 'succeeded'
    assert view['units'][1]['allowed_actions'] == []
    assert view['units'][1]['provenance']['kind'] == 'model_retry'
    attempt['response'] = [dict(start=0, end=0.5, text='tampered')]
    with pytest.raises(Conflict, match='retained_evidence_invalid'):
        RoleUnitRecovery(runtime).inspect('owner', job, run)


def test_unsupported_role_does_not_read_source():
    runtime, job, run = runtime_fixture()
    runtime.database.rows['model_role_tasks'][0]['envelope']['role'] = 'other'
    view = RoleUnitRecovery(runtime).inspect('owner', job, run)
    assert not view['supported']
    assert runtime.store.reads == 0
