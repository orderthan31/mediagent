"""Host archival preserves private source bytes, never invents body provenance."""
import json
from pathlib import Path

from mideagent_controlnet.agent_pool_host import PoolHost
from video_service.private_task_console import WITHHELD, read_private_console
from video_service.task_console import read_console

TASK = 'a' * 32
INSTANCE = 'c' * 32
AT = '2026-11-13T12:00:00+00:00'
SECRET = 'LEGACY_PRIVATE_ARCHIVE_SENTINEL'


def host(root):
    value = object.__new__(PoolHost)
    value.root = root
    return value


def test_private_legacy_bytes_preserved_without_minting_diagnostic_provenance(tmp_path):
    folder = tmp_path / INSTANCE / 'console'
    folder.mkdir(parents=True)
    source = folder / (TASK + '.jsonl')
    # An unmarked historical diagnostic-shaped body is still private text.
    diagnostic = dict(event='mideagent.tool.v1', role='translation', state='completed',
                      tool_id='text.translate', index=0)
    rows = [dict(task_id=TASK, at=AT, stream='stderr', text=SECRET + ' 日本語'),
            dict(task_id=TASK, at=AT, stream='stdout', text=json.dumps(diagnostic))]
    raw = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    source.write_bytes(raw)
    host(tmp_path).archive_console(dict(id=INSTANCE, role='translation'))
    archived = tmp_path / 'console' / source.name
    assert source.read_bytes() == archived.read_bytes() == raw
    view = read_private_console(TASK, root=archived.parent)
    assert [row['text'] for row in view['lines']] == [WITHHELD, WITHHELD]
    assert SECRET not in json.dumps(view)
    assert all('private_console_policy' not in json.loads(row) for row in raw.splitlines())


def test_generic_role_archival_keeps_existing_visible_freeform_behavior(tmp_path):
    folder = tmp_path / INSTANCE / 'console'
    folder.mkdir(parents=True)
    source = folder / (TASK + '.jsonl')
    source.write_text(json.dumps(dict(task_id=TASK, at=AT, stream='stdout',
                                     text='actual generic diagnostic')) + '\n')
    host(tmp_path).archive_console(dict(id=INSTANCE, role='encode'))
    view = read_console(TASK, root=tmp_path / 'console')
    assert [row['text'] for row in view['lines']] == ['actual generic diagnostic']
    assert 'content_policy' not in view


def test_private_host_rejects_symlink_and_invalid_task_filename(tmp_path):
    folder = tmp_path / INSTANCE / 'console'
    folder.mkdir(parents=True)
    outside = tmp_path / 'outside'
    raw = json.dumps(dict(task_id=TASK, at=AT, stream='stdout', text=SECRET)) + '\n'
    outside.write_text(raw)
    (folder / (TASK + '.jsonl')).symlink_to(outside)
    (folder / 'invalid-task.jsonl').write_text(raw)
    host(tmp_path).archive_console(dict(id=INSTANCE, role='translation'))
    assert not list((tmp_path / 'console').glob('*.jsonl'))
    assert outside.read_text() == raw
