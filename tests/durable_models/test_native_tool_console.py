"""Local native console proofs: real tools/threads/files, no provider or broker I/O."""
import hashlib
import io
import json
import sys
import threading
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest

from mideagent_agents.tool_binding import invoke
from mideagent_agents.transcription.model_graph import TranscriptionAgent
from mideagent_model_runtime.broker import DeliveryHeld, RoleReceiver
from video_service.content_store import ContentStore
from video_service.role_task_contracts import InvalidRoleDelivery


@pytest.fixture
def native(tmp_path, monkeypatch):
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(tmp_path / 'status' / 'status.json'))
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path / 'wrong-root'))
    return stdout, stderr, tmp_path / 'status' / 'console', monkeypatch


def rows(root, task):
    return [json.loads(line) for line in (root / (task + '.jsonl')).read_text().splitlines()]


def events(root, task, event='mideagent.tool.v1'):
    result = []
    for row in rows(root, task):
        try:
            value = json.loads(row['text'])
        except ValueError:
            continue
        if value.get('event') == event:
            result.append(value)
    return result


def case(tmp_path, native, model=lambda *_: []):
    # Install during the test call, not fixture setup (pytest resets its streams).
    native[3].setattr(sys, 'stdout', native[0])
    native[3].setattr(sys, 'stderr', native[1])
    path = tmp_path / 'input.wav'
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b'\0\0' * 32000)
    task = {'version': 1, 'task_id': 'a' * 32, 'role': 'transcription',
            'audio': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size},
            'model': {'model_id': 'b' * 32, 'revision': 1}, 'source_language': 'auto',
            'chunk_frames': 16000, 'max_calls': 4,
            'timeline': [{'packed_start': 0, 'packed_end': 2, 'source_start': 10, 'source_end': 12}]}
    agent = TranscriptionAgent(tmp_path / 'state', model, chunk_concurrency=2)
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'outputs').mkdir()
    inputs = ContentStore(tmp_path / 'inputs')
    outputs = ContentStore(tmp_path / 'outputs')
    ref = inputs.put('c' * 32, [path.read_bytes()], 'audio')
    packet = {'version': 1, 'role': 'transcription', 'task': task,
              'source': {'owner': 'c' * 32, 'reference': ref}, 'output_owner': 'c' * 32}
    return agent, task, RoleReceiver(agent, inputs, outputs), packet


def test_actual_graph_delivery_native_plan_and_no_replay_fabrication(tmp_path, native):
    gate = threading.Barrier(2)
    calls = []
    def model(*_):
        calls.append(threading.get_ident())
        gate.wait(timeout=10)
        print('real model stdout')
        print('real model stderr', file=sys.stderr)
        return []
    agent, task, receiver, packet = case(tmp_path, native, model)
    result = receiver.deliver(packet)
    assert result['status'] == 'completed'
    tool = events(native[2], task['task_id'])
    assert len(calls) == 2 and len(set(calls)) == 2
    assert [(e['state'], e.get('planned_segments')) for e in tool if e['tool_id'] == 'speech.prepare_audio'] == [('started', None), ('completed', 2)]
    transcribe = [e for e in tool if e['tool_id'] == 'speech.transcribe']
    assert sorted((e['index'], e['state']) for e in transcribe) == [(0, 'completed'), (0, 'started'), (1, 'completed'), (1, 'started')]
    assert all(e['elapsed_ms'] >= 0 for e in tool if e['state'] != 'started')
    assert all('planned_segments' not in e for e in transcribe)
    archived = rows(native[2], task['task_id'])
    assert any(r['text'] == '[output body withheld]' and r['stream'] == 'stdout' for r in archived)
    assert any(r['text'] == '[output body withheld]' and r['stream'] == 'stderr' for r in archived)
    assert native[0].getvalue() and native[1].getvalue()
    assert all(json.loads(line)['task_id'] == task['task_id'] for stream in native[:2] for line in stream.getvalue().splitlines())
    assert not (tmp_path / 'wrong-root').exists()
    before = list(tool)
    assert receiver.deliver(packet) == result
    assert events(native[2], task['task_id']) == before
    assert len(calls) == 2
    lifecycle = events(native[2], task['task_id'], 'mideagent.delivery.v1')
    assert [e['state'] for e in lifecycle] == ['received', 'completed', 'received', 'completed']
    with agent.state.connect() as db:
        assert db.execute('SELECT count(*) FROM standard_tool_calls').fetchone()[0] == 2


def test_explicit_task_binding_in_fresh_tool_threads(tmp_path, native):
    agent, task, _, _ = case(tmp_path, native)
    barrier = threading.Barrier(2)
    def run(identity):
        bound = dict(task, task_id=identity)
        def execute():
            barrier.wait(timeout=10)
            print(identity, end='')
            print('error ' + identity, file=sys.stderr)
            return {'value': identity}
        return invoke(agent, bound, 'speech.transcribe', execute, index=7)
    ids = ['a' * 32, 'd' * 32]
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(run, ids)) == [{'value': i} for i in ids]
    for identity, other in [ids, ids[::-1]]:
        text = (native[2] / (identity + '.jsonl')).read_text()
        assert identity in text and other not in text
        assert [e['state'] for e in events(native[2], identity)] == ['started', 'completed']
        assert all(e['index'] == 7 for e in events(native[2], identity))


@pytest.mark.parametrize('status', ['failed', 'held', 'cancelled'])
def test_failed_or_held_return_not_completed(tmp_path, native, status):
    agent, task, _, _ = case(tmp_path, native)
    value = {'status': status, 'error': 'secret-body', 'transcript': 'private-transcript'}
    assert invoke(agent, task, 'speech.transcribe', lambda: value) is value
    emitted = events(native[2], task['task_id'])
    assert [e['state'] for e in emitted] == ['started', status]
    assert 'secret-body' not in native[0].getvalue()
    assert 'private-transcript' not in native[0].getvalue()


def test_exception_identity_and_sensitive_output_redaction(tmp_path, native):
    agent, task, _, _ = case(tmp_path, native)
    error = type('caller-secret-class', (RuntimeError,), {})('prompt=private-prompt https://user:pass@host/private?token=sentinel')
    def execute():
        print('Authorization: Bearer sentinel-auth')
        print('caller_token=sentinel-caller', file=sys.stderr)
        print('transcript=sentinel-transcript')
        print('prompt=sentinel-prompt')
        print('https://private.example/sentinel-path?key=sentinel-url')
        print('password=sentinel-password', end='', file=sys.stderr)
        raise error
    with pytest.raises(RuntimeError) as raised:
        invoke(agent, task, 'speech.transcribe', execute)
    assert raised.value is error
    combined = ''.join(s.getvalue() for s in native[:2]) + (native[2] / (task['task_id'] + '.jsonl')).read_text()
    for secret in ['sentinel-', 'private.example', 'caller-secret-class', 'private-prompt']:
        assert secret not in combined
    emitted = events(native[2], task['task_id'])
    assert emitted[-1]['state'] == 'failed'
    assert emitted[-1]['error_type'] == 'Exception'
    assert emitted[-1]['error_code'] == 'tool_exception'


def test_console_io_failures_do_not_replace_return_or_exception(tmp_path, native, monkeypatch):
    class Broken:
        def write(self, text):
            raise OSError('native broken')
        def flush(self):
            raise OSError('native flush broken')
    agent, task, _, _ = case(tmp_path, native)
    monkeypatch.setattr(sys, 'stdout', Broken())
    monkeypatch.setattr(sys, 'stderr', Broken())
    def execute():
        print('actual stdout')
        print('actual stderr', file=sys.stderr)
        return 19
    assert invoke(agent, task, 'speech.transcribe', execute) == 19
    assert events(native[2], task['task_id'])[-1]['state'] == 'completed'
    error = ValueError('original')
    def fail():
        print('partial', end='')
        raise error
    with pytest.raises(ValueError) as raised:
        invoke(agent, task, 'speech.transcribe', fail)
    assert raised.value is error
    # An unusable archive parent also cannot consume a call or change its result.
    blocked = tmp_path / 'blocked'
    blocked.write_text('not a directory')
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(blocked / 'status.json'))
    assert invoke(agent, task, 'speech.transcribe', execute) == 19


def test_worker_held_and_invalid_real_boundary(tmp_path, native):
    def model(*_):
        raise TimeoutError('private model failure')
    _, task, receiver, packet = case(tmp_path, native, model)
    assert receiver.deliver(packet)['status'] == 'held'
    assert events(native[2], task['task_id'], 'mideagent.delivery.v1')[-1]['state'] == 'held'
    changed = dict(packet, output_owner='d' * 32)
    with pytest.raises(InvalidRoleDelivery):
        receiver.deliver(changed)
    assert events(native[2], task['task_id'], 'mideagent.delivery.v1')[-1]['state'] == 'error'
    assert 'private model failure' not in native[0].getvalue()


def test_worker_exception_hold_not_retried_or_released(tmp_path, native, monkeypatch):
    agent, task, receiver, packet = case(tmp_path, native)
    calls = []
    def fail(*_):
        calls.append(1)
        print('real agent stdout')
        print('real agent stderr', file=sys.stderr)
        raise RuntimeError('secret exception body')
    monkeypatch.setattr(agent, 'run', fail)
    with pytest.raises(DeliveryHeld, match='role_operation_held'):
        receiver.deliver(packet)
    with pytest.raises(DeliveryHeld, match='artifact_delivery_held'):
        receiver.deliver(packet)
    assert calls == [1]
    assert not events(native[2], task['task_id'])
    assert [e['state'] for e in events(native[2], task['task_id'], 'mideagent.delivery.v1')] == ['received', 'held', 'received', 'held']
    assert 'secret exception body' not in native[0].getvalue()


def test_unknown_result_shape_does_not_change_return(tmp_path, native):
    agent, task, _, _ = case(tmp_path, native)
    value = {'status': ['not', 'a', 'state']}
    assert invoke(agent, task, 'speech.transcribe', lambda: value) is value
    assert events(native[2], task['task_id'])[-1]['state'] == 'completed'


def test_prepare_does_not_consume_iterators_or_infer_plan(tmp_path, native):
    agent, task, _, _ = case(tmp_path, native)
    touched = []
    def generate():
        touched.append(1)
        yield 'private audio'
    value = generate()
    assert invoke(agent, task, 'speech.prepare_audio', lambda: value) is value
    assert touched == []
    assert all('planned_segments' not in e for e in events(native[2], task['task_id']))
    assert invoke(agent, task, 'speech.prepare_audio', lambda: []) == []
    assert events(native[2], task['task_id'])[-1]['planned_segments'] == 0


def test_source_identity_still_enforced_inside_standard_tool(tmp_path, native, monkeypatch):
    import mideagent_agents.tool_binding as binding
    original = binding.standard_tools
    def tools(*args):
        tool = original(*args)[0]
        invoke_actual = tool.invoke
        def changed(value):
            return invoke_actual({'source': dict(value['source'], sha256='f' * 64)})
        class Changed:
            invoke = staticmethod(changed)
        return [Changed()]
    monkeypatch.setattr(binding, 'standard_tools', tools)
    agent, task, _, _ = case(tmp_path, native)
    calls = []
    with pytest.raises(ValueError, match='bound_tool_input_changed'):
        invoke(agent, task, 'speech.transcribe', lambda: calls.append(1))
    assert calls == []
    assert events(native[2], task['task_id'])[-1]['state'] == 'failed'


def test_json_credentials_and_body_labels_are_redacted(tmp_path, native):
    agent, task, _, _ = case(tmp_path, native)
    def execute():
        print(json.dumps({'api_key': 'sentinel-json-key'}))
        print(json.dumps({'Authorization': 'sentinel-auth'}))
        print(json.dumps({'caller_token': 'sentinel-token'}))
        print(json.dumps({'audio': 'sentinel-audio'}))
        print('postgresql://user:sentinel-password@host/database')
    invoke(agent, task, 'speech.transcribe', execute)
    text = (native[2] / (task['task_id'] + '.jsonl')).read_text()
    assert 'sentinel-' not in text
    assert 'sentinel-' not in native[0].getvalue()


def test_logging_serializer_failure_does_not_replace_execution(tmp_path, native, monkeypatch):
    import mideagent_agents.tool_events as diagnostics
    agent, task, _, _ = case(tmp_path, native)
    class BrokenJSON:
        @staticmethod
        def dumps(*args, **kwargs):
            raise RuntimeError('logging failure')
    monkeypatch.setattr(diagnostics, 'json', BrokenJSON)
    value = object()
    assert invoke(agent, task, 'speech.transcribe', lambda: value) is value
    error = RuntimeError('original')
    def fail():
        raise error
    with pytest.raises(RuntimeError) as raised:
        invoke(agent, task, 'speech.transcribe', fail)
    assert raised.value is error


def test_archive_cap_and_symlink_do_not_affect_native_or_execution(tmp_path, native):
    from video_service import task_console
    agent, task, _, _ = case(tmp_path, native)
    native[2].mkdir(parents=True)
    archive = native[2] / (task['task_id'] + '.jsonl')
    archive.write_bytes(b' ' * task_console._LIMIT)
    assert invoke(agent, task, 'speech.transcribe', lambda: 42) == 42
    assert archive.stat().st_size == task_console._LIMIT
    assert 'mideagent.tool.v1' in native[0].getvalue()
    archive.unlink()
    target = tmp_path / 'untouched'
    target.write_text('do not overwrite')
    archive.symlink_to(target)
    assert invoke(agent, task, 'speech.transcribe', lambda: 42) == 42
    assert target.read_text() == 'do not overwrite'


def test_console_context_restored_after_exception(tmp_path, native):
    from video_service import task_console
    agent, task, _, _ = case(tmp_path, native)
    def fail():
        print('partial-error', end='', file=sys.stderr)
        raise ValueError('not logged')
    with pytest.raises(ValueError):
        invoke(agent, task, 'speech.transcribe', fail)
    assert task_console._context.get() is None
    before = (native[2] / (task['task_id'] + '.jsonl')).read_bytes()
    print('outside-task')
    assert (native[2] / (task['task_id'] + '.jsonl')).read_bytes() == before
    assert native[0].getvalue().endswith('outside-task\n')
    # Private partial text is withheld at write time, not buffered past failure.
    assert any(r['text'] == '[output body withheld]' and r['stream'] == 'stderr'
               for r in rows(native[2], task['task_id']))
    assert events(native[2], task['task_id'])[-1]['state'] == 'failed'


def test_translation_prepare_reports_only_concrete_plan(tmp_path, native):
    from types import SimpleNamespace
    from mideagent_agents.registry import registration
    base, task, _, _ = case(tmp_path, native)
    agent = SimpleNamespace(state=base.state, registration=registration('translate'))
    task = dict(task, transcript=task['audio'])
    del task['audio']
    result = [{'text': 'private-source'}, {'text': 'private-context'}]
    assert invoke(agent, task, 'text.prepare_batches', lambda: result) is result
    emitted = events(native[2], task['task_id'])
    assert all(e['role'] == 'translation' for e in emitted)
    assert emitted[-1]['planned_segments'] == 2
    assert 'private-source' not in native[0].getvalue()
    assert 'private-context' not in native[0].getvalue()


def test_subprocess_native_stdout_stderr_match_task_archive(tmp_path, native):
    import os
    import subprocess
    _, task, _, _ = case(tmp_path, native)
    program = '''
import json, sys
from pathlib import Path
from mideagent_agents.transcription.model_graph import TranscriptionAgent
from mideagent_agents.tool_binding import invoke
agent = TranscriptionAgent(Path(sys.argv[1]) / 'child-state', lambda *_: [])
task = json.loads(sys.argv[2])
calls = []
error = ValueError('exception-body-not-emitted')
def execute():
    calls.append(1)
    print('native child stdout')
    print('native child stderr', file=sys.stderr)
    print('api_key=sentinel-child', file=sys.stderr)
    raise error
try:
    invoke(agent, task, 'speech.transcribe', execute, index=12)
except ValueError as actual:
    assert actual is error
else:
    raise AssertionError('exception lost')
assert calls == [1]
'''
    result = subprocess.run(
        [sys.executable, '-c', program, str(tmp_path), json.dumps(task)],
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)),
    )
    assert result.returncode == 0, result.stderr
    stdout = [json.loads(line) for line in result.stdout.splitlines()]
    stderr = [json.loads(line) for line in result.stderr.splitlines()]
    assert stdout and stderr
    archived = rows(native[2], task['task_id'])
    assert [row for row in archived if row['stream'] == 'stdout'] == stdout
    assert [row for row in archived if row['stream'] == 'stderr'] == stderr
    assert all(row['task_id'] == task['task_id'] for row in stdout + stderr)
    assert 'sentinel-child' not in result.stderr
    assert 'exception-body-not-emitted' not in result.stdout + result.stderr
    assert [e['state'] for e in events(native[2], task['task_id'])] == ['started', 'failed']
