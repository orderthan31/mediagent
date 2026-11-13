"""Offline HTTP transport proofs; no provider, worker, database or deployment."""
import io
import json
import sys
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from mideagent_model_tools import bridge
from video_service import task_console

TASK = 'a' * 32
TOKEN = 'private-token-' * 4


@pytest.fixture
def console(tmp_path, monkeypatch):
    root = tmp_path / 'console'
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(root))
    return root, monkeypatch


def streams(console):
    out, err = io.StringIO(), io.StringIO()
    console[1].setattr(sys, 'stdout', out)
    console[1].setattr(sys, 'stderr', err)
    return out, err


def records(console):
    path = console[0] / (TASK + '.jsonl')
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def events(console):
    values = []
    for row in records(console):
        try:
            value = json.loads(row['text'])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('event') == 'mideagent.tool_transport.v1':
            values.append(value)
    return values


def request(invoke, payload, *, role='transcription', path='/speech', token=TOKEN):
    fake = SimpleNamespace(invoke=invoke, invoke_translation=invoke,
                           invoke_vocalization=invoke, roles=object())
    with bridge.ToolServer(('127.0.0.1', 0), fake, TOKEN, role=role) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        conn = HTTPConnection(*server.server_address, timeout=5)
        try:
            conn.request('POST', path, json.dumps(payload),
                         {'Authorization': 'Bearer ' + token})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()
            thread.join(timeout=5)
            assert not thread.is_alive()


@pytest.mark.parametrize('role,path', [('transcription', '/speech'),
    ('translation', '/translate'), ('vocalization', '/vocal')])
def test_real_http_boundary_and_result(console, role, path):
    out, err = streams(console)
    calls = []
    def invoke(payload):
        calls.append(payload)
        print('actual tool stdout')
        print('actual tool stderr', file=sys.stderr)
        return {'status': 'held', 'result': 'sentinel-result'}
    payload = {'task_id': TASK, 'prompt': 'sentinel-request',
               'root': '/sentinel-root', 'role': 'sentinel-role', 'call_index': True}
    status, body = request(invoke, payload, role=role, path=path)
    assert status == 200 and json.loads(body) == {'status': 'held', 'result': 'sentinel-result'}
    assert calls == [payload]
    assert events(console) == [
        {'event': 'mideagent.tool_transport.v1', 'role': role, 'operation': 'invoke', 'state': state}
        for state in ['received', 'completed']]
    # Private free-form output is withheld; real stream/task/native tee remains.
    archived = records(console)
    assert [r for r in archived if r['stream'] == 'stdout'] == [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r for r in archived if r['stream'] == 'stderr'] == [json.loads(line) for line in err.getvalue().splitlines()]
    assert any(r['text'] == '[output body withheld]' and r['stream'] == 'stdout' for r in records(console))
    assert any(r['text'] == '[output body withheld]' and r['stream'] == 'stderr' for r in records(console))
    assert 'sentinel-' not in out.getvalue() + err.getvalue()
    assert task_console._context.get() is None


def test_http_failure_redacts_both_streams_and_exception(console):
    out, err = streams(console)
    error = type('sentinel-class', (RuntimeError,), {} )('sentinel-exception')
    error.http_status = 'sentinel-status'
    error.upstream_detail = 'sentinel-detail'
    def invoke(_):
        for stream in [sys.stdout, sys.stderr]:
            print(TOKEN, file=stream)
            print('https://sentinel-host/sentinel-path?q=sentinel-query', file=stream)
            print('{"prompt": "sentinel-prompt"}', file=stream)
            print('Authorization: sentinel-auth', file=stream)
            print('transcript=sentinel-transcript', end='', file=stream)
        raise error
    assert request(invoke, {'task_id': TASK}) == (409, b'{"error":"scoped_call_held"}')
    text = out.getvalue() + err.getvalue() + json.dumps(records(console))
    assert 'sentinel-' not in text and TOKEN not in text
    assert events(console)[-1] == {'event': 'mideagent.tool_transport.v1',
        'role': 'transcription', 'operation': 'invoke', 'state': 'failed',
        'error_type': 'Exception', 'error_code': 'transport_exception'}


@pytest.mark.parametrize('payload,token,path,status', [
    ({'task_id': '../escape'}, TOKEN, '/speech', 409),
    ({'task_id': TASK}, 'wrong', '/speech', 403),
    ({'task_id': TASK}, TOKEN, '/unknown', 403),
    ([], TOKEN, '/speech', 409),
])
def test_rejected_http_has_no_scope_or_invocation(console, payload, token, path, status):
    streams(console)
    calls = []
    assert request(lambda p: calls.append(p), payload, token=token, path=path)[0] == status
    assert calls == [] and not console[0].exists()


def test_storage_lease_distinct_from_tool_invocation(console, monkeypatch):
    from video_service.role_storage_leases import RoleStorageLeases
    streams(console)
    calls = []
    monkeypatch.setattr(RoleStorageLeases, 'grant', lambda self, p: {'lease': 'sentinel-lease'})
    status, body = request(lambda p: calls.append(p), {'task_id': TASK}, path='/speech/storage-lease')
    assert status == 200 and json.loads(body) == {'lease': 'sentinel-lease'}
    assert calls == []
    assert [e['operation'] for e in events(console)] == ['storage_lease', 'storage_lease']


@pytest.mark.parametrize('broken', ['native', 'archive', 'serializer'])
def test_logging_failures_preserve_http_outcome(console, monkeypatch, tmp_path, broken):
    streams(console)
    if broken == 'native':
        class Broken:
            def write(self, value): raise OSError('sink failed')
            def flush(self): raise OSError('sink failed')
        monkeypatch.setattr(sys, 'stdout', Broken())
        monkeypatch.setattr(sys, 'stderr', Broken())
    elif broken == 'archive':
        console[0].write_text('blocked directory')
    else:
        monkeypatch.setattr(bridge, '_emit_boundary', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('sink')))
    calls = []
    def invoke(_):
        calls.append(1)
        print('partial', end='')
        print('partial error', end='', file=sys.stderr)
        return {'ok': True}
    assert request(invoke, {'task_id': TASK}) == (200, b'{"ok":true}')
    assert calls == [1]
    def fail(_):
        print('partial failure', end='')
        raise ValueError('sentinel-failure')
    assert request(fail, {'task_id': TASK}) == (409, b'{"error":"scoped_call_held"}')


@pytest.mark.parametrize('broken_logging', [False, True])
def test_direct_boundary_preserves_result_and_baseexception_identity(console, monkeypatch, broken_logging):
    streams(console)
    if broken_logging:
        monkeypatch.setattr(bridge, '_emit_boundary', lambda *a: (_ for _ in ()).throw(OSError('sink')))
    value = object()
    assert bridge._invoke_observed(TASK, TOKEN, 'transcription', 'invoke', lambda: value) is value
    for error in [ValueError('sentinel-error'), KeyboardInterrupt(), SystemExit(7)]:
        def fail():
            print('partial', end='')
            raise error
        with pytest.raises(type(error)) as raised:
            bridge._invoke_observed(TASK, TOKEN, 'transcription', 'invoke', fail)
        assert raised.value is error
        assert task_console._context.get() is None


def test_parallel_http_scopes_and_no_startup_or_outside_task_events(console):
    from concurrent.futures import ThreadPoolExecutor
    out, err = streams(console)
    gate = threading.Barrier(2)
    calls = []
    def invoke(payload):
        calls.append(payload['task_id'])
        gate.wait(timeout=5)
        print('task ' + payload['task_id'], end='')
        print('stderr ' + payload['task_id'], end='', file=sys.stderr)
        return {'ok': True}
    fake = SimpleNamespace(invoke=invoke, invoke_translation=invoke, invoke_vocalization=invoke)
    with bridge.ToolServer(('127.0.0.1', 0), fake, TOKEN) as server:
        assert not console[0].exists()
    identities = [TASK, 'b' * 32]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda identity: request(invoke, {'task_id': identity}), identities))
    assert results == [(200, b'{"ok":true}')] * 2
    assert sorted(calls) == identities
    for identity, other in [identities, identities[::-1]]:
        text = (console[0] / (identity + '.jsonl')).read_text()
        assert identity in text and other not in text
    before = (console[0] / (TASK + '.jsonl')).read_bytes()
    print('outside task')
    assert (console[0] / (TASK + '.jsonl')).read_bytes() == before
    assert task_console._context.get() is None


def test_archive_symlink_not_followed(console, tmp_path):
    streams(console)
    console[0].mkdir()
    target = tmp_path / 'untouched'
    target.write_text('unchanged')
    (console[0] / (TASK + '.jsonl')).symlink_to(target)
    assert request(lambda _: {'ok': True}, {'task_id': TASK}) == (200, b'{"ok":true}')
    assert target.read_text() == 'unchanged'
