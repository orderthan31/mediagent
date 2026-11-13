"""Private model-role pre-tee boundary, independent of legacy capture setup.

Raw Python stdout/stderr is *always* withheld in a private scope, not classified
by keys, lines or JSON shape. One marker per stream/scope reports actual output.
Only the opaque capability yielded to boundary code can emit bounded diagnostics;
writing the same bytes to stdout never grants that capability. This is not a
sandbox for hostile Python code, cached streams, native fd writes or subprocesses.
The process-wide router is stable; identities and capabilities are context-local.
Outside private scopes the existing generic console behavior is unchanged.
"""
import contextlib
import contextvars
import datetime
import json
import math
import os
import stat
from pathlib import Path
import sys

from video_service import task_console

_scope: contextvars.ContextVar[dict | None] = contextvars.ContextVar('private_task_console', default=None)
WITHHELD = '[output body withheld]'
_POLICY = 'private-pretee-v1'


def _safe_diagnostic(text):
    """Validate metadata *after* provenance/capability, never promote raw output."""
    if type(text) is not str or len(text) > 4096 or '\n' in text or '\r' in text:
        return False
    try:
        row = json.loads(text)
        if type(row) is not dict:
            return False
        event, role, state = (row.get(k) for k in ('event', 'role', 'state'))
        if type(role) is not str or role not in {'transcription', 'translation', 'vocalization'}:
            return False
        definitions = {
            'mideagent.tool.v1': ({'tool_id', 'index'}, {'started', 'completed', 'failed', 'held', 'cancelled'}, {'tool_exception'}),
            'mideagent.delivery.v1': ({'kind'}, {'received', 'completed', 'failed', 'held', 'cancelled', 'error'}, {'delivery_held', 'delivery_exception'}),
            'mideagent.tool_transport.v1': ({'operation'}, {'received', 'completed', 'failed'}, {'transport_exception'}),
        }
        if type(event) is not str or event not in definitions:
            return False
        required, states, errors = definitions[event]
        keys = {'event', 'role', 'state'} | required
        if (not keys <= row.keys() or row.keys() - keys -
                {'elapsed_ms', 'planned_segments', 'error_type', 'error_code'}):
            return False
        if type(state) is not str or state not in states:
            return False
        tools = {
            'transcription': {'media.analyze', 'media.extract_audio', 'media.preprocess_audio',
                              'speech.prepare_audio', 'speech.transcribe', 'speech.validate_chunk', 'speech.merge_segments'},
            'translation': {'text.prepare_batches', 'text.translate', 'text.validate_batch', 'text.merge_batches'},
            'vocalization': set(),
        }
        if event == 'mideagent.tool.v1':
            if (type(row['tool_id']) is not str or row['tool_id'] not in tools[role]
                    or type(row['index']) is not int or not 0 <= row['index'] < 2**31):
                return False
        if 'kind' in row and row['kind'] not in {'result', 'cancel_ack'}:
            return False
        if 'operation' in row and row['operation'] not in {'invoke', 'storage_lease'}:
            return False
        if 'elapsed_ms' in row:
            elapsed = row['elapsed_ms']
            if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or not 0 <= elapsed < 2**53:
                return False
        if 'planned_segments' in row:
            if (row.get('tool_id') not in {'speech.prepare_audio', 'text.prepare_batches'}
                    or type(row['planned_segments']) is not int or not 0 <= row['planned_segments'] < 2**31):
                return False
        if 'error_type' in row or 'error_code' in row:
            if (row.get('error_type') not in {'ValueError', 'TypeError', 'RuntimeError', 'TimeoutError', 'OSError', 'EOFError', 'Exception'}
                    or row.get('error_code') not in errors):
                return False
        # Only the producer's canonical spelling is admissible. A permissive
        # JSON parse alone would hide earlier duplicate-key body values while
        # returning the original, still-sensitive serialized text to readers.
        return text == json.dumps(row, separators=(',', ':'))
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def read_private_console(task_id, *, root=None):
    """Project legacy private bodies as withheld without rewriting archive bytes.

    The marker is owned by the pre-tee collector, never inferred from body JSON.
    Historical unmarked diagnostics are withheld too: provenance is unavailable.
    """
    task_console._identity(task_id)
    folder = root or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT')
    empty = {'lines': [], 'available': False, 'truncated': False,
             'content_policy': 'private_diagnostics_v1'}
    if not folder:
        return empty
    path = Path(folder) / (task_id + '.jsonl')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return empty
            raw = stream.read(task_console._LIMIT)
    except OSError:
        return empty
    lines = []
    for item in raw.decode('utf8', errors='replace').splitlines():
        try:
            row = json.loads(item)
            if (type(row) is not dict or row.get('task_id') != task_id
                    or row.get('stream') not in {'stdout', 'stderr'}):
                continue
            at = row.get('at')
            if type(at) is not str or len(at) > 40 or datetime.datetime.fromisoformat(at).tzinfo is None:
                continue
            text = row.get('text')
            trusted = (set(row) == {'task_id', 'at', 'stream', 'text', 'private_console_policy'}
                       and row.get('private_console_policy') == _POLICY)
            visible = text if trusted and (text == WITHHELD or _safe_diagnostic(text)) else WITHHELD
            lines.append({'at': at, 'stream': row['stream'], 'text': visible})
        except (ValueError, TypeError, RecursionError):
            continue
    return {'lines': lines, 'available': True, 'truncated': len(raw) >= task_console._LIMIT,
            'content_policy': 'private_diagnostics_v1'}



class _BinaryStream:
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        if _scope.get() is None:
            return self.stream.target.buffer.write(data)
        if data:
            self.stream._withhold()
        return len(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream.target.buffer, name)


class _PrivateStream(task_console._Stream):
    @property
    def buffer(self):
        return _BinaryStream(self)

    def write(self, text):
        if _scope.get() is None:
            if isinstance(self.target, task_console._Stream):
                return self.target.write(text)
            return super().write(text)
        if text:
            self._withhold()
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def record(self, context, line):
        if _scope.get() is not None:
            self._withhold()
        elif isinstance(self.target, task_console._Stream):
            self.target.record(context, line)
        else:
            super().record(context, line)

    def _withhold(self):
        scope = _scope.get()
        if scope is not None and self.kind not in scope['seen']:
            scope['seen'].add(self.kind)
            self._record_safe(scope, WITHHELD)

    def _record_safe(self, scope, text):
        # Called only with the fixed marker or through the emission capability.
        # Never pass raw writes, exception objects or legacy pending buffers here.
        if not scope['task']:
            return
        try:
            row = {'task_id': scope['task'],
                   'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'stream': self.kind, 'text': text, 'private_console_policy': _POLICY}
            encoded = json.dumps(row, ensure_ascii=False) + '\n'
            target = self.target
            while isinstance(target, task_console._Stream):
                target = target.target
            with task_console._lock:
                try:
                    target.write(encoded)
                    target.flush()
                except BaseException:
                    pass
                # A broken native sink must not prevent the independent archive.
                try:
                    if scope['root']:
                        folder = Path(scope['root'])
                        folder.mkdir(parents=True, exist_ok=True)
                        path = folder / (scope['task'] + '.jsonl')
                        if path.is_symlink():
                            return
                        if not path.exists() or path.stat().st_size < task_console._LIMIT:
                            with path.open('a', encoding='utf8', newline='') as archive:
                                archive.write(encoded)
                except BaseException:
                    pass
        except BaseException:
            # Instrumentation failures cannot replace an invocation/cancellation.
            pass

    def flush(self):
        if _scope.get() is None:
            return self.target.flush()
        try:
            self.target.flush()
        except BaseException:
            pass


def _install():
    with task_console._lock:
        for name in ('stdout', 'stderr'):
            stream = getattr(sys, name)
            if not isinstance(stream, _PrivateStream):
                setattr(sys, name, _PrivateStream(stream, name))


@contextlib.contextmanager
def private_capture(task_id, *, root=None, root_factory=None, secrets=(), legacy_capture=None):
    """Bind privacy *before* attempting optional legacy capture, even if it fails.

    The yielded callable is scoped to this exact entry, revoked on exit and not
    available by printing a magic field. Producers must construct diagnostics
    solely from fixed identifiers and bounded numeric metadata, never tool bodies.
    No per-task sys redirect and no raw pending buffer are used.
    """
    _install()
    try:
        identity = task_console._identity(task_id)
    except Exception:
        identity = None  # Unbound/invalid worker metadata: suppress, never leak.
    scope = {'task': identity, 'root': root or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT'),
             'seen': set(), 'active': True}
    private_token = _scope.set(scope)
    previous = task_console._context.set(task_console._context.get())
    manager = None

    def emit(text):
        if (_scope.get() is scope and scope['active'] and type(text) is str
                and _safe_diagnostic(text)):
            stream = sys.stdout
            if isinstance(stream, _PrivateStream):
                stream._record_safe(scope, text)

    try:
        if root_factory is not None:
            # Metadata resolution is also inside the privacy boundary. Failure
            # disables this archive, not invocation, and never chooses a new root.
            scope['root'] = None
            try:
                scope['root'] = root_factory() or os.environ.get('MIDEAGENT_TASK_CONSOLE_ROOT')
            except BaseException:
                pass
        if legacy_capture is not None:
            try:
                candidate = legacy_capture(task_id, root=scope['root'], secrets=secrets)
                candidate.__enter__()
                manager = candidate
            except BaseException:
                pass
        yield emit
    finally:
        try:
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except BaseException:
                    pass
        finally:
            scope['active'] = False
            task_console._context.reset(previous)
            _scope.reset(private_token)
