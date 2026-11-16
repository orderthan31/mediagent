"""Offline producer timeout evidence; no provider, broker or PostgreSQL I/O."""
import copy
import hashlib
import io
import json
import threading
import urllib.error
from types import SimpleNamespace
from email.message import Message

import pytest

from mideagent_model_runtime import cli
from mideagent_agents.translation.model_graph import TranslationAgent
from video_service.diagnostic_codes import failure_code, mark_tool_transport_timeout


CODE = 'tool_transport_timeout_outcome_unknown'


def config(**changes):
    return {'tool_contract': 'registry_translation_v1',
            'tool_url': 'https://bridge.invalid/translate',
            'credential_env': 'TEST_TOOL_TOKEN', **changes}


@pytest.mark.parametrize('bad', [True, False, 0, -1, float('nan'), float('inf'), -float('inf'), '60', None])
def test_nonfinite_or_non_numeric_timeouts_rejected(bad):
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(bad, provider_timeout_seconds=60)
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(135, provider_timeout_seconds=bad)


@pytest.mark.parametrize('bad', [True, 0, -1, 61, float('inf'), float('nan'), '15'])
def test_overhead_must_be_positive_finite_and_bounded(bad):
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(135, provider_timeout_seconds=60, overhead_seconds=bad)


def test_coordination_defaults_and_explicit_short_wait_fail_closed(monkeypatch):
    assert cli.coordinated_tool_timeout(provider_timeout_seconds=60) == 75
    assert cli.coordinated_tool_timeout(75, provider_timeout_seconds=60) == 75
    assert cli.coordinated_tool_timeout(provider_timeout_seconds=120) == 135
    with pytest.raises(ValueError, match='tool_timeout_below_provider_budget'):
        cli.coordinated_tool_timeout(25, provider_timeout_seconds=60)
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(provider_timeout_seconds=1e309)
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(provider_timeout_seconds=1e308)
    with pytest.raises(ValueError):
        cli.coordinated_tool_timeout(provider_timeout_seconds=10**1000)
    # Validation runs before credential/HTTP construction. No implicit repair of
    # an explicitly too-short existing worker configuration.
    with pytest.raises(ValueError, match='tool_timeout_below_provider_budget'):
        cli.ScopedTranslationTool(config(timeout_seconds=25))
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    original = config()
    before = copy.deepcopy(original)
    assert cli.ScopedTranslationTool(original).timeout == 135
    assert original == before
    assert cli.ScopedTranslationTool(config(timeout_seconds=140)).timeout == 140


@pytest.mark.parametrize('bad', [True, float('inf'), float('nan')])
def test_other_scoped_tools_also_reject_nonfinite_waits(bad):
    with pytest.raises(ValueError, match='finite_tool_timeout_required'):
        cli.ScopedSpeechTool(config(tool_contract='controlled_v1', timeout_seconds=bad))


@pytest.mark.parametrize('wrapped', [False, True])
@pytest.mark.parametrize('phase', ['open', 'read'])
def test_only_http_timeout_is_classified_and_original_exception_retained(monkeypatch, wrapped, phase):
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    tool = cli.ScopedTranslationTool(config())
    timeout = TimeoutError('private-url-token')
    error = urllib.error.URLError(timeout) if wrapped else timeout
    calls = []
    class Reply(io.BytesIO):
        def read(self, *_):
            raise error
    def open_request(*args, **kwargs):
        calls.append(kwargs['timeout'])
        if phase == 'open':
            raise error
        return Reply()
    tool.client = SimpleNamespace(open=open_request)
    with pytest.raises(type(error)) as raised:
        tool._post({'private': 'body'})
    assert raised.value is error
    if wrapped:
        assert isinstance(error, urllib.error.URLError) and error.reason is timeout
    assert failure_code(error, 'tool_exception') == CODE
    assert calls == [135]


@pytest.mark.parametrize('error', [ValueError('timed out'), TimeoutError('not an HTTP boundary'),
    urllib.error.URLError('timed out'), RuntimeError('private'),
    urllib.error.HTTPError('https://private', 504, 'timed out', Message(), None)])
def test_text_and_unmarked_timeout_do_not_infer_provider_failure(error):
    assert failure_code(error, 'tool_exception') == 'tool_exception'


def test_explicit_adapter_code_is_never_relabelled():
    error = TimeoutError('private')
    setattr(error, 'code', 'invalid_response')
    mark_tool_transport_timeout(error)
    assert failure_code(error, 'tool_exception') == 'invalid_response'


def test_diagnostic_annotation_failure_preserves_exception(monkeypatch):
    class ImmutableTimeout(TimeoutError):
        def __setattr__(self, name, value):
            raise RuntimeError('cannot annotate')
    error = ImmutableTimeout('original')
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    tool = cli.ScopedTranslationTool(config())
    def fail(*a, **kw):
        raise error
    tool.client = SimpleNamespace(open=fail)
    with pytest.raises(ImmutableTimeout) as raised:
        tool._post({})
    assert raised.value is error


@pytest.mark.parametrize('error', [
    urllib.error.URLError(ConnectionRefusedError('private')),
    urllib.error.URLError('timed out'),
    urllib.error.HTTPError('https://private', 504, 'timed out', Message(), None),
])
def test_http_other_failures_are_not_timeout_and_no_resend(monkeypatch, error):
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    tool = cli.ScopedTranslationTool(config())

    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise error
    tool.client = SimpleNamespace(open=fail)
    with pytest.raises(urllib.error.URLError) as raised:
        tool._post({})
    assert raised.value is error
    assert failure_code(error, 'tool_exception') == 'tool_exception'
    assert calls == [1]


@pytest.mark.parametrize('body,maximum,error_type', [
    (b'not-json', 100, json.JSONDecodeError),
    (b'{}', 1, ValueError),
])
def test_decoder_and_response_budget_failures_are_not_loosened(monkeypatch, body, maximum, error_type):
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    tool = cli.ScopedTranslationTool(config(max_reply_bytes=maximum))
    calls = []
    def reply(*a, **kw):
        calls.append(1)
        return io.BytesIO(body)
    tool.client = SimpleNamespace(open=reply)
    with pytest.raises(error_type) as raised:
        tool._post({})
    assert failure_code(raised.value, 'tool_exception') == 'tool_exception'
    assert calls == [1]


def test_late_bridge_failure_is_separate_from_local_unknown_no_replay(tmp_path, monkeypatch):
    monkeypatch.setenv('TEST_TOOL_TOKEN', 'offline')
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(tmp_path / 'status.json'))
    tool = cli.ScopedTranslationTool(config())
    rows = [{'id': 'cue-0', 'start': 0, 'end': 1, 'text': 'offline'}]
    raw = json.dumps(rows).encode()
    path = tmp_path / 'input.json'
    path.write_bytes(raw)
    task = {'version': 1, 'role': 'translation', 'task_id': 'a' * 32,
            'transcript': {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)},
            'models': [{'model_id': 'b' * 32, 'revision': 3},
                       {'model_id': 'c' * 32, 'revision': 7}],
            'source_language': 'en', 'target_language': 'ko',
            'batch_policy': 'bounded_100x16k_v1', 'max_calls': 2}
    frozen = copy.deepcopy(task)
    release, finished = threading.Event(), threading.Event()
    ledger = {'status': 'started', 'error_code': None, 'response': None}
    calls, threads = [], []
    original = TimeoutError('private socket message')
    def late_bridge():
        try:
            assert release.wait(5)
            ledger.update(status='failed', error_code='invalid_response', response=None)
        finally:
            finished.set()
    def open_request(request, **kwargs):
        calls.append(json.loads(request.data))
        worker = threading.Thread(target=late_bridge)
        threads.append(worker)
        worker.start()
        raise original
    tool.client = SimpleNamespace(open=open_request)
    agent = TranslationAgent(tmp_path / 'state', tool)
    try:
        first = agent.run(task, path)
        assert first['status'] == 'held' and first['model_calls'] == 1
        local = agent.state.chunk(task['task_id'], 0)
        assert local['status'] == 'unknown' and local['error'] == 'TimeoutError'
        assert ledger['status'] == 'started' and not finished.is_set()
        release.set()
        assert finished.wait(5)
        assert ledger == {'status': 'failed', 'error_code': 'invalid_response', 'response': None}
        before = agent.state.task(task['task_id'])
        assert agent.run(task, path) == first
        assert agent.state.task(task['task_id']) == before
        assert agent.state.chunk(task['task_id'], 0) == local
        assert agent.state.chunk(task['task_id'], 1) is None
        # A fresh role object over the same local durable state cannot reset
        # the call budget or turn a late Bridge result into a replay request.
        resumed = TranslationAgent(tmp_path / 'state', tool)
        try:
            assert resumed.run(task, path) == first
            assert resumed.state.task(task['task_id']) == before
        finally:
            resumed.connection.close()
        assert task == frozen and len(calls) == 1
        assert calls[0]['candidate_index'] == 0
        events = [json.loads(json.loads(line)['text']) for line in
                  (tmp_path / 'console' / (task['task_id'] + '.jsonl')).read_text().splitlines()]
        failed = [e for e in events if e.get('tool_id') == 'text.translate' and e['state'] == 'failed']
        assert len(failed) == 1
        assert failed[0]['error_code'] == CODE and failed[0]['error_type'] == 'TimeoutError'
        assert failed[0]['unit_index'] == 0 and failed[0]['candidate_index'] == 0
        assert 'private socket message' not in json.dumps(events)
        assert failure_code(original, 'tool_exception') == CODE
        # The task-log projection continues to report the original ledger fact,
        # not the producer's independent timeout classification.
        from video_service.postgres.task_logs import project_logs, ERRORS
        projected = project_logs(
            {'id': 'd' * 32, 'node_id': 'e' * 32, 'node_type': 'translate', 'status': 'held'},
            {'role': 'translation', 'phase': 'held', 'candidate_count': 2},
            [{'chunk_index': 0, 'created_at': None, **ledger}])
        assert any(ERRORS['invalid_response'] in row['message'] for row in projected['entries'])
        assert all(ERRORS[CODE] not in row['message'] for row in projected['entries'])
        assert ledger['error_code'] == 'invalid_response' and ledger['response'] is None
    finally:
        release.set()
        for worker in threads:
            worker.join(5)
            assert not worker.is_alive()
        agent.connection.close()
