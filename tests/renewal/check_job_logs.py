"""No-network producer -> host archive -> bounded reader -> authenticated route."""
import io
import json
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from video_service.postgres import Missing, Conflict
from video_service.postgres import job_logs
from video_service.private_task_console import _POLICY, _safe_diagnostic
from mideagent_agents import tool_events

TASK = 'a' * 32
JOB = 'b' * 32
OWNER = 'c' * 32
OTHER = 'd' * 32
AT = '2026-11-13T12:00:00+00:00'
SECRET = 'PRIVATE_PROMPT_AND_RESPONSE_SENTINEL'


def run(identity=TASK, kind='transcribe', **extra):
    return dict(id=identity, node_id='agent-node', node_type=kind, status='running',
                error_code=None, started_at=AT, completed_at=None, **extra)


class Database:
    def __init__(self, runs=None, roles=None, calls=None):
        self.runs = [run()] if runs is None else runs
        self.roles = roles or {}
        self.calls = calls or {}
        self.jobs = [dict(owner_id=OWNER, id=JOB)]
        self.queries = []
        self.open = False

    @contextmanager
    def connection(self):
        self.open = True
        try:
            yield self
        finally:
            self.open = False

    def execute(self, sql, params=()):
        assert self.open
        assert sql.startswith(('SELECT', 'SET TRANSACTION READ ONLY'))
        self.queries.append((sql, params))
        if sql.startswith('SET'):
            rows = []
        elif 'FROM jobs ' in sql:
            assert params == (JOB,)
            rows = self.jobs
        elif 'FROM node_runs ' in sql:
            assert params[:2] == (OWNER, JOB)
            # Schema regression: node_runs has no created_at column.
            assert 'ORDER BY created_at' not in sql
            rows = self.runs[:params[-1]]
        elif 'to_regclass' in sql:
            rows = [dict(value='model_role_tasks')]
        elif 'FROM model_role_tasks ' in sql:
            assert params[:2] == (OWNER, JOB)
            rows = [self.roles[params[-1]]] if params[-1] in self.roles else []
        elif 'FROM model_role_tool_calls' in sql:
            rows = self.calls.get(params[0], [])[:params[1]]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: rows[0] if rows else None, fetchall=lambda: rows)


def app_for(db):
    from app.renewal_routes import mount_runtime
    app = FastAPI()

    def session(request: Request):
        if request.headers.get('test-session') != 'authenticated':
            raise HTTPException(401)
        return {'user': {'id': OTHER}}

    runtime = SimpleNamespace(database=db, store=None)
    mount_runtime(app, runtime, session, session, local_execution=False)
    return app


def write_archive(root, texts, *, task=TASK, private=False, at=AT):
    root.mkdir(parents=True, exist_ok=True)
    rows = [dict(task_id=task, at=at, stream='stderr', text=text,
                 **({'private_console_policy': _POLICY} if private else {})) for text in texts]
    path = root / (task + '.jsonl')
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return path


def test_emitter_archive_removed_worker_reader_api(tmp_path, monkeypatch):
    from mideagent_controlnet.agent_pool_host import PoolHost
    instance = 'e' * 32
    worker = tmp_path / instance
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(worker / 'status.json'))
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path / 'console'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    answer = {'status': 'failed', 'error': 'rate_limited', 'body': SECRET}
    calls = []

    def invoke(source):
        calls.append(source)
        print(SECRET)
        print(json.dumps({'event': 'mideagent.tool.v1', 'role': 'transcription',
                          'state': 'completed', 'tool_id': 'speech.transcribe', 'index': 999}))
        return answer

    assert tool_events.invoke_observed(SimpleNamespace(invoke=invoke), {}, task_id=TASK,
        role='transcription', identity='speech.transcribe', index=5,
        unit_index=2, candidate_index=1) is answer
    assert len(calls) == 1
    host = object.__new__(PoolHost)
    host.root = tmp_path
    host.archive_console({'id': instance, 'role': 'transcription'})
    shutil.rmtree(worker)  # only this test's temporary worker; persisted archive survives
    raw = (tmp_path / 'console' / (TASK + '.jsonl')).read_bytes()
    assert SECRET.encode() not in raw
    db = Database()
    original = job_logs.read_private_console

    def read(*args, **kwargs):
        assert not db.open
        return original(*args, **kwargs)

    monkeypatch.setattr(job_logs, 'read_private_console', read)
    client = TestClient(app_for(db))
    url = '/api/renewal/jobs/' + JOB + '/logs'
    assert client.get(url).status_code == 401
    assert db.queries == []
    response = client.get(url, headers={'test-session': 'authenticated'})
    assert response.status_code == 200
    value = response.json()
    events = [r for r in value['records'] if r['source'] == 'diagnostic']
    assert [r['level'] for r in events] == ['INFO', 'ERROR']
    assert all(r['at'] and r['unit_index'] == 2 and r['candidate_index'] == 1 for r in events)
    assert events[-1]['error_code'] == 'rate_limited' and events[-1]['elapsed_ms'] >= 0
    assert all('raw' not in r for r in value['records'])
    assert SECRET not in response.text and '999' not in response.text
    assert value['total_records'] == len(value['records']) == 3
    assert value['has_more'] is False and value['truncated'] is False
    assert value['sources'] == [dict(run_id=TASK, node_id='agent-node', available=True,
        raw_available=False, policy='private_diagnostics_v1', truncated=False)]
    assert (tmp_path / 'console' / (TASK + '.jsonl')).read_bytes() == raw
    # The authenticated actor differs from storage owner, exactly as shared reads allow.
    routes = {r.path: r for r in client.app.routes if hasattr(r, 'dependant')}
    assert routes['/api/renewal/jobs/{identity}/logs'].dependant.dependencies[0].call is \
        routes['/api/renewal/jobs/{identity}/runs/{run_id}/logs'].dependant.dependencies[0].call


def test_exception_is_not_replayed_or_serialized(tmp_path, monkeypatch):
    from mideagent_model_tools.endpoints import EndpointFailure
    monkeypatch.delenv('MIDEAGENT_INSTANCE_STATUS_FILE', raising=False)
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    error = EndpointFailure(SECRET, code='authentication_failed')
    invoked = []

    def fail(_):
        invoked.append(1)
        raise error

    with pytest.raises(EndpointFailure) as caught:
        tool_events.invoke_observed(SimpleNamespace(invoke=fail), {}, task_id=TASK,
            role='translation', identity='text.translate', index=4, unit_index=2, candidate_index=0)
    assert caught.value is error and invoked == [1]
    value = job_logs.JobLogs(SimpleNamespace(database=Database())).get(OTHER, JOB)
    event = value['records'][-1]
    assert event['error_code'] == 'authentication_failed'
    assert event['error_type'] == 'Exception' and event['level'] == 'ERROR'
    assert SECRET not in json.dumps(value)


def test_binding_uses_frozen_width_not_operation_index(tmp_path, monkeypatch):
    from mideagent_agents.tool_binding import invoke
    monkeypatch.delenv('MIDEAGENT_INSTANCE_STATUS_FILE', raising=False)
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    connection = sqlite3.connect(':memory:')
    from mideagent_agents.registry import registration
    agent = SimpleNamespace(registration=registration('translation'),
                            state=SimpleNamespace(connect=lambda: connection))
    task = {'task_id': TASK, 'models': [{}, {}], 'transcript': {'sha256': 'f' * 64, 'bytes': 1}}
    assert invoke(agent, task, 'text.validate_batch', lambda: [], index=5) == []
    assert invoke(agent, task, 'text.prepare_batches', lambda: [], index=5) == []
    rows = job_logs.JobLogs(SimpleNamespace(database=Database())).get(OTHER, JOB)['records']
    validate = [r for r in rows if r.get('tool_id') == 'text.validate_batch']
    assert all(r['unit_index'] == 2 and r['candidate_index'] == 1 for r in validate)
    assert all('unit_index' not in r for r in rows if r.get('tool_id') == 'text.prepare_batches')


def test_legacy_unknown_stderr_stale_and_secret_suppression(tmp_path, monkeypatch):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    old = json.dumps(dict(event='mideagent.tool.v1', role='transcription', state='failed',
                         tool_id='speech.transcribe', index=9), separators=(',', ':'))
    write_archive(tmp_path, [old], private=True)
    cpu = OTHER
    write_archive(tmp_path, ['plain stderr', 'ERROR actual failure',
        'https://user:' + SECRET + '@host/file?token=' + SECRET,
        'postgresql://user:' + SECRET + '@host/db', 'Authorization: Bearer ' + SECRET], task=cpu, at=None)
    stale = dict(task_id='f' * 32, at=AT, stream='stdout', text=SECRET)
    with (tmp_path / (TASK + '.jsonl')).open('a') as stream:
        stream.write(json.dumps(stale) + '\n')
    db = Database([run(), run(cpu, 'encode')])
    value = job_logs.JobLogs(SimpleNamespace(database=db)).get(OTHER, JOB)
    old_event = next(r for r in value['records'] if r['run_id'] == TASK)
    assert old_event['level'] == 'UNKNOWN' and 'unit_index' not in old_event and 'raw' not in old_event
    stderr = next(r for r in value['records'] if r['message'] == 'plain stderr')
    assert stderr['level'] == 'UNKNOWN' and stderr['at'] is None
    assert next(r for r in value['records'] if r['message'] == 'ERROR actual failure')['level'] == 'ERROR'
    assert SECRET not in json.dumps(value)
    assert value['sources'][1]['raw_available'] is True


def test_failure_ledger_is_not_fake_emission(tmp_path, monkeypatch):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    role = dict(task_id=TASK, candidate_count=2, phase='held', held_reason=SECRET)
    calls = [dict(chunk_index=5, status='failed', error_code='rate_limited'),
             dict(chunk_index=6, status='unknown', error_code=SECRET)]
    db = Database(roles={TASK: role}, calls={TASK: calls})
    value = job_logs.JobLogs(SimpleNamespace(database=db)).get(OTHER, JOB)
    assert value['total_records'] == 3
    assert all(r['at'] is None and r['source'] == 'stored_failure' and
               r['provenance'] == 'recorded_state' and 'raw' not in r for r in value['records'])
    record = next(r for r in value['records'] if r.get('error_code') == 'rate_limited')
    assert record['unit_index'] == 2 and record['candidate_index'] == 1
    assert SECRET not in json.dumps(value)
    assert value['sources'][0]['available'] is False


def test_bounds_run_call_byte_and_output_windows(tmp_path, monkeypatch):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    monkeypatch.setattr(job_logs, 'MAX_RUNS', 1)
    monkeypatch.setattr(job_logs, 'MAX_CALLS', 1)
    monkeypatch.setattr(job_logs, 'MAX_RECORDS', 1)
    monkeypatch.setattr(job_logs, 'ARCHIVE_BYTES', 400)
    write_archive(tmp_path, ['x' * 50] * 20)
    db = Database([run(), run(OTHER)], roles={TASK: dict(task_id=TASK, candidate_count=2, phase='sent')},
                  calls={TASK: [dict(chunk_index=i, status='failed', error_code='rate_limited') for i in range(3)]})
    original = job_logs.read_private_console
    reads = []
    def reader(*args, **kwargs):
        assert not db.open
        reads.append(kwargs['limit'])
        return original(*args, **kwargs)
    monkeypatch.setattr(job_logs, 'read_private_console', reader)
    value = job_logs.JobLogs(SimpleNamespace(database=db)).get(OTHER, JOB)
    assert reads == [400] and len(value['sources']) == 1 and len(value['records']) == 1
    expected_lines = len(original(TASK, limit=400)['lines'])
    assert value['total_records'] == expected_lines + 1
    assert value['has_more'] and value['truncated'] and value['sources'][0]['truncated']


def test_missing_duplicate_and_malformed_job_reject_before_archive(monkeypatch):
    monkeypatch.setattr(job_logs, 'read_private_console', lambda *a, **k: pytest.fail('archive read'))
    db = Database()
    logs = job_logs.JobLogs(SimpleNamespace(database=db))
    with pytest.raises(ValueError):
        logs.get(OTHER, '../escape')
    assert not db.queries
    db.jobs = []
    with pytest.raises(Missing):
        logs.get(OTHER, JOB)
    db.jobs = [dict(owner_id=OWNER, id=JOB)] * 2
    with pytest.raises(Conflict):
        logs.get(OTHER, JOB)


@pytest.mark.parametrize('cap', ['MAX_RUNS', 'MAX_CALLS', 'ARCHIVE_BYTES', 'MAX_RECORDS'])
def test_each_cap_reports_omissions_independently(tmp_path, monkeypatch, cap):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    write_archive(tmp_path, ['first', 'second'])
    roles = {TASK: dict(task_id=TASK, candidate_count=2, phase='sent')}
    calls = {TASK: [dict(chunk_index=i, status='failed', error_code='rate_limited') for i in range(2)]}
    db = Database([run(), run(OTHER)], roles, calls)
    monkeypatch.setattr(job_logs, cap, 1)
    value = job_logs.JobLogs(SimpleNamespace(database=db)).get(OTHER, JOB)
    assert value['has_more'] and value['truncated']
    if cap == 'MAX_RUNS':
        assert len(value['sources']) == 1 and value['total_records'] == 4
        assert not value['sources'][0]['truncated']  # omitted run, not this source
    elif cap == 'MAX_CALLS':
        assert value['total_records'] == 3 and value['sources'][0]['truncated']
    elif cap == 'ARCHIVE_BYTES':
        assert value['total_records'] == 2 and value['sources'][0]['truncated']
    else:
        assert value['total_records'] == 4 and len(value['records']) == 1
        assert value['sources'][0]['truncated']


def test_exact_read_window_is_not_falsely_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    path = write_archive(tmp_path, ['one'])
    monkeypatch.setattr(job_logs, 'ARCHIVE_BYTES', path.stat().st_size)
    value = job_logs.JobLogs(SimpleNamespace(database=Database())).get(OTHER, JOB)
    assert value['total_records'] == 1 and not value['truncated'] and not value['has_more']


def test_empty_archive_does_not_synthesize_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    value = job_logs.JobLogs(SimpleNamespace(database=Database())).get(OTHER, JOB)
    assert value['records'] == [] and value['total_records'] == 0
    assert not value['sources'][0]['available'] and not value['sources'][0]['raw_available']
    assert not value['has_more'] and not value['truncated']


@pytest.mark.parametrize('changes', [dict(unit_index=True), dict(candidate_index=-1),
    dict(unit_index=2**31), dict(error_code=SECRET), dict(error_type=SECRET),
    dict(level='DEBUG'), dict(level='INFO'), dict(prompt=SECRET)])
def test_extended_private_schema_is_closed(changes):
    event = dict(event='mideagent.tool.v1', role='transcription', state='failed',
                 tool_id='speech.transcribe', index=5, level='ERROR',
                 unit_index=2, candidate_index=1, error_code='rate_limited')
    assert _safe_diagnostic(json.dumps(event, separators=(',', ':')))
    event.update(changes)
    assert not _safe_diagnostic(json.dumps(event, separators=(',', ':')))


@pytest.mark.parametrize('status,level,code', [('failed', 'ERROR', 'request_rejected'),
    ('unknown', 'WARNING', 'outcome_unknown'), ('held', 'WARNING', 'model_reply_unknown')])
def test_transport_real_failure_code_preserves_reply(tmp_path, monkeypatch, status, level, code):
    from mideagent_model_tools.bridge import _invoke_observed
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    reply = dict(status=status, error=code, body=SECRET)
    assert _invoke_observed(TASK, 'token' * 10, 'transcription', 'invoke', lambda: reply) is reply
    value = job_logs.JobLogs(SimpleNamespace(database=Database())).get(OTHER, JOB)
    assert [r['level'] for r in value['records']] == ['INFO', level]
    assert value['records'][-1]['error_code'] == code
    assert SECRET not in json.dumps(value)
