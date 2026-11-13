"""Recorded prepare metadata only; local files/tools, no provider or live DB."""
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime/controlnet'))
sys.path.insert(0, str(ROOT / 'apps/orchestrator'))
sys.path.insert(0, str(ROOT / 'tests/renewal'))

from mideagent_agents import tool_events
from mideagent_controlnet.agent_pool_host import PoolHost
from video_service.postgres import task_logs
from check_task_log_progress import FakeDatabase, call, role, run

TASK = 'b' * 32
INSTANCE = 'c' * 32


def metadata(**changes):
    return dict(version=1, task_id=TASK, role='translation',
                tool_id='text.prepare_batches', planned_segments=3, **changes)


@pytest.fixture
def native(tmp_path, monkeypatch):
    private = tmp_path / INSTANCE / 'console'
    private.mkdir(parents=True)
    monkeypatch.setenv('MIDEAGENT_INSTANCE_STATUS_FILE', str(private.parent / 'status.json'))
    monkeypatch.setenv('MIDEAGENT_TASK_CONSOLE_ROOT', str(tmp_path / 'console'))
    monkeypatch.setattr(sys, 'stdout', io.StringIO())
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    host = object.__new__(PoolHost)
    host.root = tmp_path
    return private, host


def invoke(value, *, identity='text.prepare_batches', name='translation', task=TASK):
    return tool_events.invoke_observed(SimpleNamespace(invoke=lambda _: value), {},
                                      task_id=task, role=name, identity=identity, index=0)


def archive(native, name='translation'):
    native[1].archive_console({'id': INSTANCE, 'role': name})


def projected(name='translation'):
    return task_logs.project_logs(run(), role(2, name=name), [
        call(0, 'failed'), call(1, 'completed'), call(2, 'unknown'),
        call(4, 'failed'), call(5, 'failed')])['progress']


def test_prepare_to_archive_to_api_projection(native, monkeypatch):
    value = [object(), object(), object()]
    assert invoke(value) is value
    path = native[0] / (TASK + '.progress.json')
    assert json.loads(path.read_text()) == metadata()
    archive(native)
    assert projected() == dict(planned_segments=3, completed_segments=1,
        failed_segments=1, active_segments=[], unresolved_segments=1,
        observed_segments=3, total_calls=5, finished_segments=2)
    # TaskLogs must look up the role task ID, not the different node-run ID.
    class TranslationDB(FakeDatabase):
        def execute(self, sql, params=()):
            result = super().execute(sql, params)
            if 'FROM model_role_tasks m ' in sql:
                return SimpleNamespace(fetchone=lambda: role(2, name='translation'))
            return result
    db = TranslationDB([call(0, 'completed')])
    response = task_logs.TaskLogs(SimpleNamespace(database=db)).get(None, 'd' * 32, 'a' * 32)
    assert response['progress']['planned_segments'] == 3
    assert all(sql.startswith(('SELECT', 'SET TRANSACTION READ ONLY')) for sql, _ in db.queries)
    assert 'private-source' not in path.read_text()


@pytest.mark.parametrize('field,value', [
    ('task_id', 'a' * 32), ('role', 'transcription'), ('tool_id', 'text.translate'),
    ('version', 2), ('version', True), ('planned_segments', True),
    ('planned_segments', -1), ('planned_segments', 2**31),
    ('planned_segments', '3'), ('extra', 'payload')])
def test_invalid_metadata_rejected_by_host_and_api(native, field, value):
    row = metadata(); row[field] = value
    (native[0] / (TASK + '.progress.json')).write_text(json.dumps(row))
    archive(native)
    shared = native[1].root / 'console' / (TASK + '.progress.json')
    assert not shared.exists()
    shared.write_text(json.dumps(row))
    assert projected()['planned_segments'] is None


@pytest.mark.parametrize('field', ['version', 'task_id', 'role', 'tool_id', 'planned_segments'])
def test_incomplete_legacy_metadata_is_unknown(native, field):
    row = metadata(); row.pop(field)
    (native[0] / (TASK + '.progress.json')).write_text(json.dumps(row))
    archive(native)
    shared = native[1].root / 'console' / (TASK + '.progress.json')
    assert not shared.exists()
    shared.write_text(json.dumps(row))
    assert projected()['planned_segments'] is None


def test_missing_legacy_and_stdout_are_not_plan(native):
    assert projected()['planned_segments'] is None
    # Even a perfectly shaped metadata body on stdout is not a sidecar.
    with tool_events.task_capture(TASK):
        print(json.dumps(metadata()))
    archive(native)
    assert projected()['planned_segments'] is None
    assert (native[1].root / 'console' / (TASK + '.jsonl')).exists()


@pytest.mark.parametrize('kind', ['symlink', 'oversize', 'fifo', 'directory', 'malformed'])
def test_unsafe_source_and_shared_metadata_rejected(native, tmp_path, kind):
    target = tmp_path / 'target'; target.write_text(json.dumps(metadata()))
    def create(path):
        if kind == 'symlink': path.symlink_to(target)
        elif kind == 'oversize': path.write_text(json.dumps(metadata()) + ' ' * 1024)
        elif kind == 'fifo': os.mkfifo(path)
        elif kind == 'directory': path.mkdir()
        else: path.write_text('{')
    create(native[0] / (TASK + '.progress.json'))
    archive(native)
    shared = native[1].root / 'console' / (TASK + '.progress.json')
    assert not shared.exists()
    create(shared)
    assert projected()['planned_segments'] is None
    assert json.loads(target.read_text()) == metadata()


def test_symlink_console_directory_rejected(native, tmp_path):
    private, host = native
    private.rmdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    private.symlink_to(outside, target_is_directory=True)
    assert invoke([]) == []
    assert not (outside / (TASK + '.progress.json')).exists()
    (outside / (TASK + '.progress.json')).write_text(json.dumps(metadata()))
    archive(native)
    shared = host.root / 'console'
    if shared.exists(): shared.rmdir()
    shared.symlink_to(outside, target_is_directory=True)
    assert projected()['planned_segments'] is None


def test_asr_clock_precedes_recorded_plan(native):
    assert invoke([1, 2], identity='speech.prepare_audio', name='transcription') == [1, 2]
    archive(native, 'transcription')
    assert projected('transcription')['planned_segments'] == 96
    mapping = role(name='transcription'); mapping['task'] = {}
    assert task_logs.project_progress(run(), mapping, [])['planned_segments'] == 2


@pytest.mark.parametrize('value', [[], {'status': 'failed'}, iter([1]), 'text'])
def test_only_concrete_prepare_list_records_plan(native, value):
    assert invoke(value) is value
    path = native[0] / (TASK + '.progress.json')
    if type(value) is list:
        assert json.loads(path.read_text())['planned_segments'] == 0
    else:
        assert not path.exists()


@pytest.mark.parametrize('task,name,identity', [('../bad', 'translation', 'text.prepare_batches'),
    (TASK, 'translation', 'speech.prepare_audio'), (TASK, 'vocalization', 'text.prepare_batches'),
    (TASK, 'translation', 'text.translate')])
def test_invalid_writer_identity_never_records(native, task, name, identity):
    assert invoke([], task=task, name=name, identity=identity) == []
    assert not list(native[0].glob('*.progress.json'))


def test_sink_failure_and_symlink_do_not_change_outcome(native, tmp_path, monkeypatch):
    target = tmp_path / 'untouched'; target.write_text('untouched')
    (native[0] / (TASK + '.progress.json')).symlink_to(target)
    class Broken:
        def write(self, *_): raise OSError('sink failure')
        def flush(self): raise OSError('sink failure')
    monkeypatch.setattr(sys, 'stdout', Broken())
    value = [1, 2]
    assert invoke(value) is value
    assert target.read_text() == 'untouched'
    error = RuntimeError('original')
    def fail(_): raise error
    with pytest.raises(RuntimeError) as raised:
        tool_events.invoke_observed(SimpleNamespace(invoke=fail), {}, task_id=TASK,
            role='translation', identity='text.prepare_batches', index=0)
    assert raised.value is error
    monkeypatch.setattr(tool_events, 'json', SimpleNamespace(dumps=lambda *_a, **_k: (_ for _ in ()).throw(OSError())))
    assert invoke(value) is value


def test_real_translation_prepare_records_batches_without_provider(native, tmp_path, monkeypatch):
    from graph_execution import translation_case
    source = [{'id': i, 'start': i, 'end': i + 1, 'text': 'private-source'}
              for i in range(201)]
    Agent, task, path = translation_case(tmp_path, source)
    task['task_id'] = TASK
    agent = Agent(tmp_path / 'state', lambda *_: pytest.fail('no provider call allowed'))
    try:
        batches = agent.prepare_task(task, path)
        assert len(batches) == 3
        assert json.loads((native[0] / (TASK + '.progress.json')).read_text()) == metadata()
        archive(native)
        # Polling can read only the 1KiB metadata, never the transcript/media.
        path.unlink()
        assert projected()['planned_segments'] == 3
    finally:
        agent.connection.close()


def test_first_record_is_immutable_and_no_private_root_fallback(native, monkeypatch):
    assert invoke([1, 2, 3]) == [1, 2, 3]
    first = (native[0] / (TASK + '.progress.json')).read_bytes()
    assert invoke([1]) == [1]
    assert (native[0] / (TASK + '.progress.json')).read_bytes() == first
    archive(native)
    assert projected()['planned_segments'] == 3
    monkeypatch.delenv('MIDEAGENT_INSTANCE_STATUS_FILE')
    assert invoke([], task='a' * 32) == []
    assert not (native[1].root / 'console' / ('a' * 32 + '.progress.json')).exists()


def test_writer_io_failure_and_broken_native_sink_are_independent(native, monkeypatch):
    class Broken:
        def write(self, *_): raise OSError('sink failure')
        def flush(self): raise OSError('sink failure')
    monkeypatch.setattr(sys, 'stdout', Broken())
    assert invoke([1, 2, 3]) == [1, 2, 3]
    assert json.loads((native[0] / (TASK + '.progress.json')).read_text()) == metadata()
    original = os.link
    def fail(*args, **kwargs):
        raise OSError('publication failure')
    monkeypatch.setattr(os, 'link', fail)
    value = [object()]
    assert invoke(value, task='a' * 32) is value
    assert not (native[0] / ('a' * 32 + '.progress.json')).exists()
    monkeypatch.setattr(os, 'link', original)
    assert not list(native[0].glob('*.progress.tmp'))


def test_wrong_instance_role_and_shared_symlink_not_published(native, tmp_path):
    assert invoke([1, 2, 3]) == [1, 2, 3]
    archive(native, 'transcription')
    shared = native[1].root / 'console' / (TASK + '.progress.json')
    assert not shared.exists()
    target = tmp_path / 'untouched'; target.write_text('untouched')
    shared.symlink_to(target)
    archive(native)
    assert target.read_text() == 'untouched'
    assert projected()['planned_segments'] is None


def test_archive_write_failure_is_best_effort(native):
    assert invoke([1]) == [1]
    shared = native[1].root / 'console'
    shared.write_text('blocked')
    # Sidecar archiving cannot hold/retry model execution through observe().
    # Remove native log to isolate the new path from existing log archival.
    (native[0] / (TASK + '.jsonl')).unlink()
    archive(native)
    assert shared.read_text() == 'blocked'
