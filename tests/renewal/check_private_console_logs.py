"""Private archive projection: read-only, authoritative DB scope, no body replay."""
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from video_service.postgres.task_logs import TaskLogs, project_logs

TASK = 'a' * 32
AT = '2026-11-13T12:00:00+00:00'
SECRET = 'LEGACY_MULTILINE_PRIVATE_BODY'


class Database:
    def __init__(self, kind, role=None, calls=()):
        self.run = dict(id=TASK, node_id='node', node_type=kind, status='running',
                        error_code=None, started_at=None, completed_at=None)
        self.role = role
        self.calls = list(calls)
        self.queries = []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=()):
        self.queries.append(sql)
        if sql.startswith('SET TRANSACTION READ ONLY') or 'FROM broker_dispatch_queue ' in sql:
            rows = []
        elif 'FROM jobs ' in sql:
            rows = [{'owner_id': 'c' * 32, 'id': 'd' * 32}]
        elif 'FROM node_runs ' in sql:
            rows = [self.run]
        elif 'to_regclass' in sql:
            rows = [{'value': 'model_role_tasks'}]
        elif 'FROM model_role_tasks m ' in sql:
            rows = [self.role] if self.role else []
        elif 'FROM model_role_tool_calls ' in sql:
            rows = self.calls
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: rows[0] if rows else None, fetchall=lambda: rows)


def archive(tmp_path, monkeypatch, texts):
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    path = tmp_path / (TASK + '.jsonl')
    rows = [dict(task_id=TASK, at=AT, stream='stderr', text=text) for text in texts]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return path


@pytest.mark.parametrize('kind,role', [
    ('transcribe', None), ('translate', None), ('vocalize', None),
    ('transcription_agent', None), ('translation_agent', None),
    ('other', dict(task_id='b' * 32, role='transcription', phase='sent')),
])
def test_legacy_private_rows_withheld_without_rewriting(tmp_path, monkeypatch, kind, role):
    path = archive(tmp_path, monkeypatch, ['{', '"prompt": [', '  "' + SECRET + '"', ']}',
        json.dumps(dict(event='mideagent.tool.v1', role='transcription', state='completed',
                        tool_id='speech.transcribe', index=42))])
    before = path.read_bytes()
    db = Database(kind, role)
    value = TaskLogs(SimpleNamespace(database=db)).get(None, 'd' * 32, TASK)
    assert SECRET not in json.dumps(value)
    assert value['console']['lines'] == [dict(at=AT, stream='stderr', text='[output body withheld]')] * 5
    assert value['console']['available'] is True
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
    assert value['entries'] == [] and value['total_calls'] == 0
    assert all(q.startswith(('SELECT', 'SET TRANSACTION READ ONLY')) for q in db.queries)


def test_nonprivate_console_remains_generic(tmp_path, monkeypatch):
    archive(tmp_path, monkeypatch, ['actual nonprivate child diagnostic'])
    value = TaskLogs(SimpleNamespace(database=Database('encode'))).get(None, 'd' * 32, TASK)
    assert value['console']['lines'] == [dict(at=AT, stream='stderr', text='actual nonprivate child diagnostic')]
    assert 'content_policy' not in value['console']


def test_real_writer_diagnostics_survive_reader_but_printed_marker_does_not(tmp_path, monkeypatch):
    import io
    import sys
    from mideagent_model_tools import bridge
    from mideagent_agents import tool_events
    from video_service import private_task_console as private
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path))
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(tmp_path / 'status.json'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    fake_event = dict(event='mideagent.tool.v1', role='transcription', state='completed',
                      tool_id='speech.transcribe', index=99)
    def invoke():
        # Even perfect collector/diagnostic shapes printed by a tool are bodies.
        print(json.dumps(dict(task_id=TASK, at=AT, stream='stdout',
            private_console_policy=private._POLICY, text=json.dumps(fake_event))))
        print(json.dumps(fake_event))
        print(SECRET, file=sys.stderr)
        return {'private': SECRET}
    assert bridge._invoke_observed(TASK, 'secret-token-' * 4, 'transcription', 'invoke', invoke) == {'private': SECRET}
    raw = (tmp_path / (TASK + '.jsonl')).read_bytes()
    value = TaskLogs(SimpleNamespace(database=Database('transcribe'))).get(None, 'd' * 32, TASK)
    assert value['console']['content_policy'] == 'private_diagnostics_v1'
    diagnostics = [json.loads(row['text']) for row in value['console']['lines'] if row['text'].startswith('{')]
    assert [row['state'] for row in diagnostics] == ['received', 'completed']
    assert all(row['event'] == 'mideagent.tool_transport.v1' for row in diagnostics)
    assert SECRET not in json.dumps(value)
    assert {r['stream'] for r in value['console']['lines'] if r['text'] == private.WITHHELD} == {'stdout', 'stderr'}
    assert (tmp_path / (TASK + '.jsonl')).read_bytes() == raw
    # Worker concrete prepare metadata remains visible, independent of API counts.
    result = [object(), object()]
    assert tool_events.invoke_observed(SimpleNamespace(invoke=lambda _: result), {},
        task_id=TASK, role='translation', identity='text.prepare_batches', index=0) is result
    worker = private.read_private_console(TASK, root=tmp_path / 'console')
    events = [json.loads(r['text']) for r in worker['lines']]
    assert [r['state'] for r in events] == ['started', 'completed']
    assert events[-1]['planned_segments'] == 2 and events[-1]['elapsed_ms'] >= 0


@pytest.mark.parametrize('changes', [
    {'extra': SECRET}, {'state': SECRET}, {'role': SECRET}, {'tool_id': SECRET},
    {'index': True}, {'index': -1}, {'index': 2**31}, {'elapsed_ms': float('nan')},
    {'elapsed_ms': -1}, {'planned_segments': [SECRET]}, {'error_type': SECRET},
])
def test_marked_but_invalid_diagnostics_withheld(tmp_path, monkeypatch, changes):
    from video_service import private_task_console as private
    diagnostic = dict(event='mideagent.tool.v1', role='transcription', state='completed',
                      tool_id='speech.transcribe', index=0)
    diagnostic.update(changes)
    path = archive(tmp_path, monkeypatch, [])
    row = dict(task_id=TASK, at=AT, stream='stdout', text=json.dumps(diagnostic),
               private_console_policy=private._POLICY)
    path.write_text(json.dumps(row) + '\n')
    before = path.read_bytes()
    view = private.read_private_console(TASK)
    assert view['lines'] == [dict(at=AT, stream='stdout', text=private.WITHHELD)]
    assert path.read_bytes() == before


def test_private_reader_bounds_identity_and_missing_policy(tmp_path, monkeypatch):
    from video_service import private_task_console as private
    path = archive(tmp_path, monkeypatch, [SECRET])
    good = dict(task_id=TASK, at=AT, stream='stderr', text=SECRET)
    invalid = [dict(good, task_id='b' * 32), dict(good, at=SECRET),
               dict(good, stream=SECRET), dict(good, at='2026-11-13T12:00:00')]
    path.write_text(''.join(json.dumps(row) + '\n' for row in invalid + [good]))
    assert private.read_private_console(TASK)['lines'] == [dict(at=AT, stream='stderr', text=private.WITHHELD)]
    absent = private.read_private_console('b' * 32)
    assert absent == dict(lines=[], available=False, truncated=False, content_policy='private_diagnostics_v1')
    monkeypatch.setattr(private.task_console, '_LIMIT', 32)
    limited = private.read_private_console(TASK)
    assert limited['truncated'] is True and limited['lines'] == []


def test_private_reader_change_preserves_global_progress_and_call_window(tmp_path, monkeypatch):
    # Equivalent count/metadata coverage to the legacy generic-reader-mock test.
    calls = [dict(chunk_index=0, status='failed', error_code=None, created_at=None),
             dict(chunk_index=1, status='completed', error_code=None, created_at=None)]
    calls += [dict(chunk_index=i * 2, status='completed', error_code=None, created_at=None) for i in range(1, 202)]
    role = dict(task_id='b' * 32, role='transcription', phase='sent', candidate_count=2)
    db = Database('transcribe', role, calls)
    path = archive(tmp_path, monkeypatch, [SECRET])
    before = path.read_bytes()
    value = TaskLogs(SimpleNamespace(database=db)).get(None, 'd' * 32, TASK)
    expected = project_logs(db.run, role, calls, display_limit=200)
    assert {key: value[key] for key in expected} == expected
    assert value['received_responses'] == 202
    assert value['progress']['completed_segments'] == 202
    assert value['progress']['observed_segments'] == 202
    assert value['progress']['total_calls'] == value['total_calls'] == 203
    assert value['shown_calls'] == 200 and value['has_more'] is True
    assert len(value['entries']) == 400
    assert value['console']['content_policy'] == 'private_diagnostics_v1'
    assert value['console']['lines'] == [dict(at=AT, stream='stderr', text='[output body withheld]')]
    assert path.read_bytes() == before
    assert SECRET not in json.dumps(value)


def test_worker_host_archive_keeps_private_diagnostic_provenance(tmp_path, monkeypatch):
    import io
    import sys
    from mideagent_agents import tool_events
    from mideagent_controlnet.agent_pool_host import PoolHost
    from video_service import private_task_console as private
    instance = 'c' * 32
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(tmp_path / instance / 'status.json'))
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path / 'console'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    value = [object(), object()]
    assert tool_events.invoke_observed(SimpleNamespace(invoke=lambda _: value), {},
        task_id=TASK, role='translation', identity='text.prepare_batches', index=0) is value
    worker_file = tmp_path / instance / 'console' / (TASK + '.jsonl')
    before = worker_file.read_bytes()
    original = private.read_private_console(TASK, root=worker_file.parent)
    host = object.__new__(PoolHost)
    host.root = tmp_path
    host.archive_console({'id': instance, 'role': 'translation'})
    projected = TaskLogs(SimpleNamespace(database=Database('translate'))).get(None, 'd' * 32, TASK)
    assert worker_file.read_bytes() == before
    assert projected['console']['lines'] == original['lines']
    assert [json.loads(row['text'])['state'] for row in projected['console']['lines']] == ['started', 'completed']


def test_duplicate_key_text_cannot_hide_a_body_from_schema_validation(tmp_path, monkeypatch):
    from video_service import private_task_console as private
    path = archive(tmp_path, monkeypatch, [])
    body = ('{"event":"' + SECRET + '","event":"mideagent.tool.v1",'
            '"role":"transcription","state":"completed",'
            '"tool_id":"speech.transcribe","index":0}')
    row = dict(task_id=TASK, at=AT, stream='stdout', text=body,
               private_console_policy=private._POLICY)
    path.write_text(json.dumps(row) + '\n')
    before = path.read_bytes()
    assert private.read_private_console(TASK)['lines'] == [dict(at=AT, stream='stdout', text=private.WITHHELD)]
    assert path.read_bytes() == before
