"""Private pre-tee boundary regressions. Arbitrary tool output is never evidence."""
import contextlib
import io
import json
import sys
from types import SimpleNamespace

import pytest

from mideagent_agents import tool_events
from mideagent_model_tools import bridge
from video_service import task_console

TASK = 'a' * 32
TOKEN = 'caller-private-' * 4
SECRET = 'SENSITIVE_PAYLOAD_SENTINEL'


@pytest.fixture
def console(tmp_path, monkeypatch):
    root = tmp_path / 'console'
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(root))
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(tmp_path / 'status.json'))
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    return root, out, err


def run(boundary, call, task=TASK):
    if boundary == 'bridge':
        return bridge._invoke_observed(task, TOKEN, 'transcription', 'invoke', call)
    return tool_events.invoke_observed(SimpleNamespace(invoke=lambda _: call()), {},
        task_id=task, role='transcription', identity='speech.transcribe', index=0)


def text(console):
    root, out, err = console
    return out.getvalue() + err.getvalue() + ''.join(p.read_text() for p in root.glob('*.jsonl'))


@pytest.mark.parametrize('boundary', ['bridge', 'worker'])
@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
@pytest.mark.parametrize('entry_failure', [False, True])
def test_exact_multiline_and_capture_entry_gaps(console, monkeypatch, boundary, stream, entry_failure):
    monkeypatch.setattr(sys, 'stdout', console[1])
    monkeypatch.setattr(sys, 'stderr', console[2])
    @contextlib.contextmanager
    def broken(*args, **kwargs):
        raise RuntimeError('capture unavailable')
        yield
    if entry_failure:
        monkeypatch.setattr(bridge if boundary == 'bridge' else task_console, 'capture_console', broken)
    calls = []
    expected = object()
    def invoke():
        calls.append(1)
        output = getattr(sys, stream)
        print('prompt=' + SECRET + ' ' + TOKEN if entry_failure else
              json.dumps({'prompt': [SECRET]}, indent=2), file=output)
        return expected
    assert run(boundary, invoke) is expected
    assert calls == [1]
    assert SECRET not in text(console) and TOKEN not in text(console)
    assert '[output body withheld]' in text(console)
    assert task_console._context.get() is None


@pytest.mark.parametrize('boundary', ['bridge', 'worker'])
def test_fake_diagnostics_unmarked_nested_fragments_are_not_trusted(console, boundary, monkeypatch):
    monkeypatch.setattr(sys, 'stdout', console[1])
    monkeypatch.setattr(sys, 'stderr', console[2])
    fake = {'event': 'mideagent.tool.v1', 'role': 'transcription', 'state': 'completed',
            'tool_id': 'speech.transcribe', 'index': 77, 'extra': SECRET}
    def invoke():
        for stream in (sys.stdout, sys.stderr):
            stream.write(json.dumps(fake) + '\n')
            stream.write(json.dumps({'outer': [{'unknown': SECRET}]}, indent=2))
            for fragment in [SECRET[:9], SECRET[9:], '\n', 'unmarked ' + SECRET]:
                stream.write(fragment)
        return {'response': SECRET}
    assert run(boundary, invoke) == {'response': SECRET}
    assert SECRET not in text(console)
    assert '"index":77' not in text(console)
    root, out, err = console
    rows = [json.loads(line) for line in (root / (TASK + '.jsonl')).read_text().splitlines()]
    assert [r for r in rows if r['stream'] == 'stdout'] == [json.loads(s) for s in out.getvalue().splitlines()]
    assert [r for r in rows if r['stream'] == 'stderr'] == [json.loads(s) for s in err.getvalue().splitlines()]
    diagnostics = [json.loads(r['text']) for r in rows if r['text'].startswith('{')]
    assert [r['state'] for r in diagnostics] == (['received', 'completed'] if boundary == 'bridge' else ['started', 'completed'])
    assert all('extra' not in r and r.get('index') != 77 for r in diagnostics)


@pytest.mark.parametrize('boundary', ['bridge', 'worker'])
@pytest.mark.parametrize('failure', ['enter', 'exit', 'native', 'archive', 'serializer'])
@pytest.mark.parametrize('outcome', ['return', 'raise', 'cancel'])
def test_faults_preserve_once_only_outcomes_and_scope(console, monkeypatch, boundary, failure, outcome):
    from video_service import private_task_console as private
    root, out, err = console
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    outer = {'task': 'd' * 32, 'root': None, 'secrets': (), 'pending': {'stdout': 'outer partial'}}
    saved = task_console._context.set(outer)
    class BrokenCapture:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            # Partial setup must not steal the parent's context or leak its own output.
            task_console._context.set({'pending': {'stderr': SECRET}})
            print(SECRET, file=sys.stderr)
            if failure == 'enter':
                raise RuntimeError(SECRET)
        def __exit__(self, *args):
            print(SECRET)
            raise RuntimeError(SECRET)
    class BrokenSink:
        def write(self, value):
            raise OSError(SECRET)
        def flush(self):
            raise OSError(SECRET)
    if failure in {'enter', 'exit'}:
        monkeypatch.setattr(bridge if boundary == 'bridge' else task_console, 'capture_console', BrokenCapture)
    elif failure == 'native':
        monkeypatch.setattr(sys, 'stdout', BrokenSink())
        monkeypatch.setattr(sys, 'stderr', BrokenSink())
    elif failure == 'archive':
        root.write_text('not a directory')
    else:
        monkeypatch.setattr(private, 'json', SimpleNamespace(
            dumps=lambda *_a, **_kw: (_ for _ in ()).throw(ValueError(SECRET)), loads=json.loads))
    expected = object()
    original = KeyboardInterrupt(SECRET) if outcome == 'cancel' else ValueError(SECRET)
    calls = []
    def invoke():
        calls.append(1)
        for stream in (sys.stdout, sys.stderr):
            stream.writelines([SECRET[:5], SECRET[5:], '\n'])
            stream.buffer.write(SECRET.encode())
            stream.flush()
        if outcome != 'return':
            raise original
        return expected
    try:
        if outcome == 'return':
            assert run(boundary, invoke) is expected
        else:
            with pytest.raises(type(original)) as raised:
                run(boundary, invoke)
            assert raised.value is original
        assert calls == [1]
        assert task_console._context.get() is outer
        assert outer['pending'] == {'stdout': 'outer partial'}
        assert private._scope.get() is None
        assert bridge._emission.get() is None and tool_events._emission.get() is None
        assert SECRET not in text(console)
    finally:
        task_console._context.reset(saved)


def test_nested_cross_boundary_contexts_and_generic_pending_are_independent(console, monkeypatch):
    from video_service.private_task_console import private_capture, read_private_console
    root, out, err = console
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    inner = 'b' * 32
    with task_console.capture_console('c' * 32, root=root):
        sys.stdout.write('generic partial ')
        outer = task_console._context.get()
        def invoke():
            print(SECRET[:9], end='')
            run('worker', lambda: print(SECRET, file=sys.stderr), task=inner)
            print(SECRET[9:], end='')
            return 19
        assert run('bridge', invoke) == 19
        assert task_console._context.get() is outer
        assert outer['pending'] == {'stdout': 'generic partial '}
        print('tail')
    generic = task_console.read_console('c' * 32, root=root)
    assert generic['lines'][0]['text'] == 'generic partial tail'
    for identity, other in [(TASK, inner), (inner, TASK)]:
        raw = (root / (identity + '.jsonl')).read_text()
        assert other not in raw and SECRET not in raw
        view = read_private_console(identity, root=root)
        assert view['content_policy'] == 'private_diagnostics_v1'
        assert any(r['text'] == '[output body withheld]' for r in view['lines'])
    # A capability is revoked on exit, and cannot target another nested scope.
    diagnostic = json.dumps(dict(event='mideagent.tool_transport.v1', role='transcription', operation='invoke', state='received'))
    with private_capture(TASK, root=root) as emit:
        with private_capture(inner, root=root):
            before = out.getvalue()
            emit(diagnostic)
            assert out.getvalue() == before
    before = out.getvalue()
    emit(diagnostic)
    assert out.getvalue() == before
    print('ordinary nonprivate output')
    assert out.getvalue().endswith('ordinary nonprivate output\n')


def test_concurrent_bridge_worker_fallbacks_do_not_mix_or_capture_other_threads(console, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    root, out, err = console
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    @contextlib.contextmanager
    def unavailable(*args, **kwargs):
        print(SECRET)
        raise OSError(SECRET)
        yield
    monkeypatch.setattr(bridge, 'capture_console', unavailable)
    monkeypatch.setattr(task_console, 'capture_console', unavailable)
    barrier = threading.Barrier(3)
    def invoke():
        barrier.wait(timeout=5)
        print(SECRET, end='')
        print(SECRET, file=sys.stderr)
        barrier.wait(timeout=5)
        return 23
    def outside():
        barrier.wait(timeout=5)
        print('unbound nonprivate positive')
        barrier.wait(timeout=5)
    with ThreadPoolExecutor(3) as pool:
        futures = [pool.submit(run, 'bridge', invoke, TASK),
                   pool.submit(run, 'worker', invoke, 'b' * 32), pool.submit(outside)]
        assert [f.result() for f in futures] == [23, 23, None]
    assert SECRET not in text(console)
    assert 'unbound nonprivate positive\n' in out.getvalue()
    for identity, other in [(TASK, 'b' * 32), ('b' * 32, TASK)]:
        raw = (root / (identity + '.jsonl')).read_text()
        assert other not in raw and 'unbound nonprivate' not in raw
        rows = [json.loads(s) for s in raw.splitlines()]
        assert {r['stream'] for r in rows if r['text'] == '[output body withheld]'} == {'stdout', 'stderr'}
        diagnostics = [json.loads(r['text']) for r in rows if r['text'].startswith('{')]
        assert len(diagnostics) == 2
        assert diagnostics[-1]['state'] == 'completed'


@pytest.mark.parametrize('outcome', ['return', 'raise'])
def test_worker_root_metadata_failure_stays_private_and_best_effort(console, monkeypatch, outcome):
    monkeypatch.setattr(sys, 'stdout', console[1])
    monkeypatch.setattr(sys, 'stderr', console[2])
    def broken_root():
        print(SECRET, file=sys.stderr)
        raise OSError('worker metadata unavailable')
    monkeypatch.setattr(tool_events, 'console_root', broken_root)
    original = ValueError(SECRET)
    calls = []
    result = object()
    def invoke():
        calls.append(1)
        print(SECRET)
        if outcome == 'raise':
            raise original
        return result
    if outcome == 'return':
        assert run('worker', invoke) is result
    else:
        with pytest.raises(ValueError) as raised:
            run('worker', invoke)
        assert raised.value is original
    assert calls == [1]
    assert SECRET not in text(console)
    assert task_console._context.get() is None


@pytest.mark.parametrize('boundary', ['bridge', 'worker'])
def test_fresh_process_real_native_fds_with_capture_failure(tmp_path, boundary):
    import os
    import subprocess
    program = '''
import contextlib, json, sys
from types import SimpleNamespace
from video_service import task_console
from mideagent_model_tools import bridge
from mideagent_agents import tool_events
@contextlib.contextmanager
def broken(*a, **kw):
    print('CHILD_PRIVATE_SENTINEL', file=sys.stderr)
    raise OSError('capture failure')
    yield
bridge.capture_console = task_console.capture_console = broken
calls = []
error = ValueError('CHILD_PRIVATE_SENTINEL')
def invoke():
    calls.append(1)
    for stream in (sys.stdout, sys.stderr):
        stream.write(json.dumps({'prompt': ['CHILD_PRIVATE_SENTINEL']}, indent=2))
        stream.write('CHILD_PRIVATE_SENTINEL')
    raise error
try:
    if sys.argv[1] == 'bridge':
        bridge._invoke_observed('a' * 32, 'private-token-' * 4, 'transcription', 'invoke', invoke)
    else:
        tool_events.invoke_observed(SimpleNamespace(invoke=lambda _: invoke()), {},
            task_id='a' * 32, role='transcription', identity='speech.transcribe', index=0)
except ValueError as actual:
    assert actual is error
else:
    raise AssertionError('exception swallowed')
assert calls == [1]
assert task_console._context.get() is None
'''
    result = subprocess.run([sys.executable, '-c', program, boundary], capture_output=True,
        text=True, timeout=30, env=dict(os.environ,
            PYTHONPATH=os.pathsep.join(sys.path),
            MIDEAGENT_TASK_CONSOLE_ROOT=str(tmp_path / 'console'),
            MIDEAGENT_INSTANCE_STATUS_FILE=str(tmp_path / 'status.json')))
    assert result.returncode == 0, result.stderr
    assert 'CHILD_PRIVATE_SENTINEL' not in result.stdout + result.stderr
    stdout = [json.loads(line) for line in result.stdout.splitlines()]
    stderr = [json.loads(line) for line in result.stderr.splitlines()]
    archived = [json.loads(line) for line in (tmp_path / 'console' / (TASK + '.jsonl')).read_text().splitlines()]
    assert stdout and stderr
    assert [r for r in archived if r['stream'] == 'stdout'] == stdout
    assert [r for r in archived if r['stream'] == 'stderr'] == stderr
    events = [json.loads(r['text']) for r in stdout if r['text'].startswith('{')]
    assert [r['state'] for r in events] == (['received', 'failed'] if boundary == 'bridge' else ['started', 'failed'])
