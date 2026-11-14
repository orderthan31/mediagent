"""Selected retry execution and immutable cross-decision success retention.

Pure service tests never invoke providers. Native cases use only the explicitly
opted-in disposable PostgreSQL fixture; no DSN is inferred.
"""
import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg import IntegrityError
from psycopg.types.json import Jsonb

from video_service.canonical import canonical, digest
from video_service.postgres import Conflict
from video_service.postgres.unit_recovery import RoleUnitRecovery
from video_service.unit_recovery import build_manifest
from test_foundation import db, admin
from test_unit_recovery_service_lifecycle import evidence, seeded, approval
from test_unit_recovery_core import fixture as core_fixture, call as core_call


class ReadOnlyRows:
    """Small read-only ledger double; all recovery validation is real service code."""
    def __init__(self, recoveries, attempts):
        self.recoveries, self.attempts = recoveries, attempts

    def execute(self, sql, params=()):
        if 'to_regclass' in sql:
            rows = [{'name': 'model_role_unit_recoveries'}]
        elif 'SELECT a.id' in sql and 'JOIN model_role_unit_recoveries' in sql:
            rows = [a for a in self.attempts if a['status'] in {'sending', 'unknown'}]
        elif 'JOIN model_role_unit_recoveries' in sql:
            a = next(a for a in self.attempts if a['id'] == params[0])
            r = self.recoveries[a['recovery_id']]
            rows = [{**a, **{k: r[k] for k in ('owner_id', 'job_id', 'run_id', 'task_id', 'context_sha256', 'request_id')}}]
        elif 'FROM model_role_unit_attempts' in sql:
            key = 'recovery_id' if 'WHERE recovery_id=' in sql else 'id'
            rows = [a for a in self.attempts if a[key] == params[0]]
        elif 'FROM model_role_unit_recoveries' in sql:
            rows = [self.recoveries[params[0]]] if params[0] in self.recoveries else []
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchall=lambda: deepcopy(rows), fetchone=lambda: deepcopy(rows[0]) if rows else None)


@pytest.fixture
def ledger(monkeypatch):
    source, pin, task, calls = evidence()
    manifest = build_manifest(task, source, calls)
    context = dict(owner_id='owner', job_id='c'*32, run_id='d'*32, task_id=task['task_id'],
                   generation=1, job_revision=7, pins_sha256=digest([pin]))
    recovery = dict(id='e'*32, owner_id='owner', job_id=context['job_id'], run_id=context['run_id'],
                    task_id=task['task_id'], revision=1, request_id='first', status='approved',
                    context=context, context_sha256=digest(context), manifest=manifest,
                    decisions=[dict(unit_index=1, action='retry', candidate_index=0)],
                    reused_attempts=[], additional_call_limit=1, approve_calls=True, prepared=None)
    attempt = dict(id='f'*32, recovery_id=recovery['id'], unit_index=1, candidate_index=0,
                   input_sha256=manifest['units'][1]['input_sha256'], status='pending',
                   terminal_sha256=None, response=None, error_code=None)
    rows = ReadOnlyRows({recovery['id']: recovery}, [attempt])
    runtime = SimpleNamespace(database=SimpleNamespace(connection=lambda: nullcontext(rows)),
                              store=SimpleNamespace(read=lambda *a, **k: canonical(source)))
    service = RoleUnitRecovery(runtime)
    facts = [dict(id=context['job_id'], revision=7, owner_id='owner'),
             dict(id=context['run_id'], request={'inputs': {'transcript': task['transcript']}}),
             dict(task_id=task['task_id'], frozen_candidates=[pin], envelope={'role':'translation','task':task}),
             recovery, context, manifest, None]
    monkeypatch.setattr(service, '_facts', lambda *a, **k: tuple(facts))
    return SimpleNamespace(service=service, rows=rows, facts=facts, recovery=recovery,
                           attempt=attempt, context=context, manifest=manifest, source=source)


def preview_body(l, decisions):
    return dict(job_revision=l.facts[0]['revision'], recovery_revision=l.facts[3]['revision'],
                context_sha256=digest(l.facts[4]), decisions=decisions)


def complete(attempt, response):
    attempt.update(status='completed', response=response, error_code=None)
    attempt['terminal_sha256'] = digest({k: attempt[k] for k in ('status','response','error_code')})


def test_selected_retry_runs_with_unresolved_suffix_and_exact_one_callback(ledger):
    l = ledger
    calls = []
    def execute(attempt_id, context_sha):
        grant = l.service.load_retry_attempt(attempt_id, context_sha)
        calls.append(grant['unit']['index'])
        complete(l.attempt, json.dumps(['retried']*100))
    l.service.executor = execute
    before = deepcopy(l.manifest)
    view = l.service.execute('owner', l.context['job_id'], l.context['run_id'], 'first')
    assert calls == [1]
    assert not view['recovery']['can_continue']
    assert view['units'][2]['status'] == 'unattempted'
    assert view['units'][1]['status'] == 'succeeded'
    assert view['units'][1]['allowed_actions'] == []
    assert l.manifest == before
    l.service.execute('owner', l.context['job_id'], l.context['run_id'], 'first')
    assert calls == [1]


def test_next_preview_retains_success_without_spending_or_edit_permission(ledger):
    l = ledger
    complete(l.attempt, json.dumps(['retried']*100))
    body = preview_body(l, [dict(unit_index=2, action='skip')])
    preview = l.service.preview('owner', l.context['job_id'], l.context['run_id'], body)
    assert preview['ready']
    assert preview['additional_call_limit'] == 0
    assert preview['execution_units'] == []
    assert [u['index'] for u in preview['retained_units']] == [0, 1]
    assert preview['reused_attempts'][0]['attempt_id'] == l.attempt['id']
    assert preview['preview_sha256'] == digest({k:v for k,v in preview.items() if k != 'preview_sha256'})
    assert preview['decisions'] == body['decisions']
    for action in ('retry', 'manual', 'skip'):
        with pytest.raises(Conflict, match='retained'):
            l.service.preview('owner', l.context['job_id'], l.context['run_id'],
                              preview_body(l, [dict(unit_index=1, action=action)]))


@pytest.mark.parametrize('role', ['translation', 'transcription'])
@pytest.mark.parametrize('action', ['skip', 'manual'])
def test_pure_mixed_retry_then_new_decision_assembles_success_without_new_call(ledger, role, action):
    l = ledger
    if role == 'transcription':
        task, source, units = core_fixture(role)
        manifest = build_manifest(task, source, [core_call(task, units, 0), core_call(task, units, 1, 'failed')])
        l.facts[5] = l.manifest = l.recovery['manifest'] = manifest
        l.facts[2]['envelope'] = {'role': role, 'task': task}
        l.attempt['input_sha256'] = manifest['units'][1]['input_sha256']
        response = core_call(task, units, 1)['response']
        manual = [dict(start=0, end=0.5, text='manual')]
    else:
        response = json.dumps(['retained-success']*100)
        manual = [{**r, 'text':'manual'} for r in l.source[200:]]
    l.recovery['decisions'].append(dict(unit_index=2, action='retry', candidate_index=0))
    l.recovery['additional_call_limit'] = 2
    failed = {**l.attempt, 'id':'a'*32, 'unit_index':2,
              'input_sha256':l.manifest['units'][2]['input_sha256'],
              'status':'failed', 'error_code':'invalid_response'}
    failed['terminal_sha256'] = digest({k:failed[k] for k in ('status','response','error_code')})
    l.rows.attempts.append(failed)
    complete(l.attempt, response)
    resolution: dict = dict(unit_index=2, action=action)
    if action == 'manual':
        resolution['value'] = manual
    before = deepcopy((l.manifest, l.rows.attempts, l.context))
    for revision in (2, 3):
        preview = l.service.preview('owner', l.context['job_id'], l.context['run_id'], preview_body(l, [resolution]))
        assert preview['ready'] and preview['additional_call_limit'] == 0
        saved = {**l.recovery, 'id':str(revision)*32, 'revision':revision, 'request_id':str(revision),
                 'decisions':preview['decisions'], 'reused_attempts':preview['reused_attempts'],
                 'additional_call_limit':0, 'approve_calls':False}
        l.rows.recoveries[saved['id']] = saved
        l.facts[3] = saved
        assembled = l.service._assemble(l.rows, saved, l.context, l.manifest)
        assert assembled['resolution_manifest']['additional_call_limit'] == 0
        assert assembled['resolution_manifest']['counts']['model_retry'] == 1
        assert assembled['resolution_manifest']['reused_attempts'][0]['attempt_id'] == l.attempt['id']
        if role == 'translation':
            assert assembled['segments'][100]['text'] == 'retained-success'
            assert len(assembled['segments']) == (201 if action == 'manual' else 200)
        else:
            assert [r['start'] for r in assembled['segments']] == ([10,20,21] if action == 'manual' else [10,20])
        l.service.executor = lambda *a: pytest.fail('carried attempts are not new call slots')
        assert l.service.execute('owner', l.context['job_id'], l.context['run_id'], saved['request_id'])['recovery']['can_continue']
    assert (l.manifest, l.rows.attempts, l.context) == before


@pytest.mark.parametrize('field', ['attempt_id', 'input_sha256', 'terminal_sha256', 'model_sha256', 'candidate_index'])
def test_persisted_carry_proof_is_reverified_not_trusted(ledger, field):
    l = ledger
    complete(l.attempt, json.dumps(['retained-success']*100))
    preview = l.service.preview('owner', l.context['job_id'], l.context['run_id'], preview_body(l, [dict(unit_index=2, action='skip')]))
    saved = {**l.recovery, 'id':'b'*32, 'revision':2, 'request_id':'second',
             'decisions':preview['decisions'], 'reused_attempts':preview['reused_attempts'], 'additional_call_limit':0}
    saved['reused_attempts'][0][field] = 1 if field == 'candidate_index' else '0'*64
    l.rows.recoveries[saved['id']] = saved
    l.facts[3] = saved
    with pytest.raises(Conflict):
        l.service.execute('owner', l.context['job_id'], l.context['run_id'], 'second')


def test_invalid_unit_index_remains_a_blocked_preview_not_an_exception(ledger):
    l = ledger
    preview = l.service.preview('owner', l.context['job_id'], l.context['run_id'],
                                preview_body(l, [dict(unit_index=[], action='retry')]))
    assert not preview['ready'] and 'unit_recovery_decision_index' in preview['blocked_reasons']


def test_new_completion_changes_preview_proof_but_not_root_context(ledger):
    l = ledger
    body = preview_body(l, [dict(unit_index=2, action='skip')])
    first = l.service.preview('owner', l.context['job_id'], l.context['run_id'], body)
    complete(l.attempt, json.dumps(['retained-success']*100))
    second = l.service.preview('owner', l.context['job_id'], l.context['run_id'], body)
    assert first['context_sha256'] == second['context_sha256']
    assert first['preview_sha256'] != second['preview_sha256']
    assert not first['ready'] and second['ready']


@pytest.mark.parametrize('damage', ['terminal', 'input', 'candidate', 'response', 'origin_context', 'origin_manifest'])
def test_completed_retry_must_have_verified_terminal_input_model_and_context(ledger, damage):
    l = ledger
    complete(l.attempt, json.dumps(['retried']*100))
    if damage == 'terminal':
        l.attempt['terminal_sha256'] = '0'*64
    elif damage == 'input':
        l.attempt['input_sha256'] = '0'*64
    elif damage == 'candidate':
        l.attempt['candidate_index'] = 10
    elif damage == 'response':
        complete(l.attempt, 'not valid JSON')
    elif damage == 'origin_context':
        l.recovery['context'] = {**l.context, 'generation': 99}
    else:
        l.recovery['manifest'] = {**l.manifest, 'source_sha256': '0'*64}
    with pytest.raises(Conflict):
        l.service.preview('owner', l.context['job_id'], l.context['run_id'], preview_body(l, []))


@pytest.mark.parametrize('changed', ['generation', 'job_revision', 'manifest'])
def test_changed_root_context_invalidates_all_carry(ledger, changed):
    l = ledger
    complete(l.attempt, json.dumps(['retried']*100))
    if changed == 'manifest':
        l.facts[5] = deepcopy(l.manifest)
        l.facts[5]['units'][1]['input_sha256'] = '0'*64
        l.facts[5]['manifest_sha256'] = digest({k:v for k,v in l.facts[5].items() if k != 'manifest_sha256'})
    else:
        l.facts[4] = {**l.context, changed: 99}
    preview = l.service.preview('owner', l.context['job_id'], l.context['run_id'],
                                preview_body(l, [dict(unit_index=1, action='retry')]))
    assert preview['reused_attempts'] == []
    assert preview['additional_call_limit'] == 1
    assert not preview['ready']


@pytest.mark.parametrize('status', ['sending', 'unknown'])
def test_ambiguous_prior_attempt_blocks_superseding_preview(ledger, status):
    l = ledger
    l.attempt['status'] = status
    with pytest.raises(Conflict, match='unresolved'):
        l.service.preview('owner', l.context['job_id'], l.context['run_id'], preview_body(l, [dict(unit_index=1, action='skip')]))


def drive(service, owner, job, run, body, *, failed=()):
    calls = []
    def executor(attempt_id, context_sha):
        grant = service.begin_attempt(attempt_id, context_sha)
        assert grant['newly_sending']
        calls.append(grant['unit_index'])
        if grant['unit_index'] in failed:
            service.finish_attempt(attempt_id, 'failed', error_code='invalid_response')
        else:
            service.finish_attempt(attempt_id, 'completed', json.dumps(['retry-success']*len(grant['unit']['source_rows'])))
    service.executor = executor
    view = service.execute(owner, job, run, body['request_id'])
    return calls, view


def test_native_selected_retry_preserves_unattempted_suffix(seeded):
    runtime, owner, job, run, _ = seeded
    service = RoleUnitRecovery(runtime)
    body = approval(service, owner, job, run, [dict(unit_index=1, action='retry')])
    service.decide(owner, job, run, body)
    calls, view = drive(service, owner, job, run, body)
    assert calls == [1]
    assert view['units'][2]['status'] == 'unattempted'
    assert not view['recovery']['can_continue']
    with pytest.raises(Conflict, match='not_ready'):
        service.prepare_adoption(owner, job, run, body['request_id'])


@pytest.mark.parametrize('action', ['manual', 'skip'])
def test_native_success_survives_new_failed_unit_decision_and_is_not_recalled(seeded, action):
    runtime, owner, job, run, source = seeded
    service = RoleUnitRecovery(runtime)
    with runtime.database.connection() as c:
        original = c.execute('SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index', (run,)).fetchall()
        root = c.execute('SELECT * FROM model_role_tasks WHERE task_id=%s', (run,)).fetchone()
    first = approval(service, owner, job, run, [dict(unit_index=i, action='retry') for i in (1,2)])
    service.decide(owner, job, run, first)
    calls, view = drive(service, owner, job, run, first, failed=(2,))
    assert calls == [1, 2] and not view['recovery']['can_continue']
    resolution = dict(unit_index=2, action=action)
    if action == 'manual':
        resolution['value'] = [{**r, 'text':'manual'} for r in source[200:]]
    second = approval(service, owner, job, run, [resolution])
    view = service.decide(owner, job, run, second)
    assert view['recovery']['additional_call_limit'] == 0 and view['recovery']['can_continue']
    assert view['units'][1]['status'] == 'succeeded' and view['units'][1]['allowed_actions'] == []
    service.executor = lambda *a: pytest.fail('retained success must not be recalled')
    service.execute(owner, job, run, second['request_id'])
    prepared = service.prepare_adoption(owner, job, run, second['request_id'])
    rows = json.loads(runtime.store.read(owner, prepared['outputs']['transcript']))
    assert rows[100]['text'] == 'retry-success'
    assert len(rows) == (201 if action == 'manual' else 200)
    with runtime.database.connection() as c:
        current = c.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s', (view['recovery']['id'],)).fetchone()
        assert len(current['reused_attempts']) == 1
        assert c.execute('SELECT count(*) AS n FROM model_role_unit_attempts WHERE recovery_id=%s', (current['id'],)).fetchone()['n'] == 0
        assert c.execute('SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index', (run,)).fetchall() == original
        assert c.execute('SELECT * FROM model_role_tasks WHERE task_id=%s', (run,)).fetchone() == root
    # Carry chains retain the original proof, not a fabricated new call.
    third = approval(service, owner, job, run, [resolution])
    again = service.decide(owner, job, run, third)
    assert again['recovery']['can_continue'] and again['recovery']['additional_call_limit'] == 0
    assert service.prepare_adoption(owner, job, run, third['request_id'])['outputs']['transcript'] == prepared['outputs']['transcript']


def test_native_carried_unit_cannot_spend_new_budget_and_old_pending_is_fenced(seeded):
    runtime, owner, job, run, _ = seeded
    service = RoleUnitRecovery(runtime)
    first = approval(service, owner, job, run, [dict(unit_index=i, action='retry') for i in (1,2)])
    state = service.decide(owner, job, run, first)
    attempts = [a for u in state['units'] for a in u['attempts'] if a['origin'] == 'recovery']
    first_id, pending_id = attempts[0]['id'], attempts[1]['id']
    service.begin_attempt(first_id, first['context_sha256'])
    service.finish_attempt(first_id, 'completed', json.dumps(['retry-success']*100))
    second = approval(service, owner, job, run, [dict(unit_index=2, action='retry')])
    state = service.decide(owner, job, run, second)
    assert state['recovery']['additional_call_limit'] == 1
    with pytest.raises(Conflict, match='not_current'):
        service.begin_attempt(pending_id, first['context_sha256'])
    with runtime.database.connection() as c:
        recovery = c.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s', (state['recovery']['id'],)).fetchone()
    with pytest.raises(IntegrityError):
        with runtime.database.connection() as c:
            c.execute("UPDATE model_role_unit_attempts SET status='sending' WHERE id=%s", (pending_id,))
    with pytest.raises(IntegrityError):
        with runtime.database.connection() as c:
            c.execute('UPDATE model_role_unit_recoveries SET reused_attempts=%s WHERE id=%s', (Jsonb([]), recovery['id']))
    with pytest.raises(IntegrityError):
        with runtime.database.connection() as c:
            c.execute('INSERT INTO model_role_unit_recoveries(id,owner_id,job_id,run_id,task_id,revision,request_id,request_sha256,context_sha256,context,manifest,decisions,reused_attempts,preview_sha256,additional_call_limit,approve_calls) SELECT %s,owner_id,job_id,run_id,task_id,revision+1,%s,request_sha256,context_sha256,context,manifest,%s,reused_attempts,preview_sha256,1,true FROM model_role_unit_recoveries WHERE id=%s',
                      (uuid4().hex, uuid4().hex, Jsonb([dict(unit_index=1,action='retry',candidate_index=0)]), recovery['id']))
    with pytest.raises(IntegrityError):
        with runtime.database.connection() as c:
            c.execute('INSERT INTO model_role_unit_attempts(id,recovery_id,unit_index,candidate_index,input_sha256) VALUES(%s,%s,1,0,%s)',
                      (uuid4().hex, recovery['id'], recovery['manifest']['units'][1]['input_sha256']))
    calls, view = drive(service, owner, job, run, second)
    assert calls == [2] and view['recovery']['can_continue']


@pytest.mark.parametrize('status', ['sending', 'unknown'])
def test_native_unknown_or_sending_cannot_be_superseded_even_after_context_change(seeded, status):
    runtime, owner, job, run, _ = seeded
    service = RoleUnitRecovery(runtime)
    first = approval(service, owner, job, run, [dict(unit_index=1, action='retry'),dict(unit_index=2, action='skip')])
    state = service.decide(owner, job, run, first)
    attempt = next(a['id'] for a in state['units'][1]['attempts'] if a['origin'] == 'recovery')
    service.begin_attempt(attempt, first['context_sha256'])
    if status == 'unknown':
        service.finish_attempt(attempt, 'unknown')
    with runtime.database.connection() as c:
        c.execute('UPDATE jobs SET revision=revision+1 WHERE id=%s', (job,))
    with pytest.raises(Conflict, match='unresolved'):
        approval(service, owner, job, run, [dict(unit_index=1, action='skip'),dict(unit_index=2, action='skip')])
