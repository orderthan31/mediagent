"""Best-effort native diagnostics at live model-role/tool boundaries only.

No input/output bodies, exception messages, DB history, or inferred progress. Each
invocation binds its task explicitly, including in LangGraph's worker threads.
"""
import contextlib
import contextvars
import math
import json
import os
from pathlib import Path
import time

from video_service import task_console
from video_service.private_task_console import private_capture


_emission = contextvars.ContextVar('private_worker_emission', default=None)


def console_root():
    status = os.environ.get('MIDEAGENT_INSTANCE_STATUS_FILE')
    return str(Path(status).parent / 'console') if status else None


@contextlib.contextmanager
def task_capture(task_id):
    with private_capture(task_id, root_factory=console_root,
                         legacy_capture=task_console.capture_console) as capability:
        previous = _emission.set(capability)
        try:
            yield
        finally:
            _emission.reset(previous)


def emit(event, role, state, *, tool_id=None, index=None, kind=None,
         started=None, planned_segments=None, error=None, error_code=None):
    """Trusted boundary metadata, never a parser/allowlist for printed bodies."""
    try:
        capability = _emission.get()
        if capability is None or role not in {'transcription', 'translation', 'vocalization'}:
            return
        states = {
            'mideagent.tool.v1': {'started', 'completed', 'failed', 'held', 'cancelled'},
            'mideagent.delivery.v1': {'received', 'completed', 'failed', 'held', 'cancelled', 'error'},
        }
        if state not in states.get(event, set()):
            return
        row = {'event': event, 'role': role, 'state': state}
        if tool_id is not None:
            from mideagent_agents.registry import registration
            registered = registration(role)
            if registered is None or tool_id not in registered['allowed_tools']:
                return
            if type(index) is not int or not 0 <= index < 2**31:
                return
            row.update(tool_id=tool_id, index=index)
        if kind is not None:
            if kind not in {'result', 'cancel_ack'}:
                return
            row['kind'] = kind
        if started is not None:
            if type(started) not in {int, float} or not math.isfinite(started):
                return
            elapsed = (time.monotonic() - started) * 1000
            if not math.isfinite(elapsed) or elapsed < 0:
                return
            row['elapsed_ms'] = round(elapsed, 3)
        if planned_segments is not None:
            if type(planned_segments) is not int or not 0 <= planned_segments < 2**31:
                return
            row['planned_segments'] = planned_segments
        if error is not None:
            allowed = {ValueError, TypeError, RuntimeError, TimeoutError, OSError, EOFError}
            row['error_type'] = type(error).__name__ if type(error) in allowed else 'Exception'
            if error_code not in {'tool_exception', 'delivery_held', 'delivery_exception'}:
                return
            row['error_code'] = error_code
        capability(json.dumps(row, separators=(',', ':')))
    except BaseException:
        pass


def result_state(result):
    if type(result) is dict:
        status = result.get('status')
        if type(status) is str and status in {'failed', 'held', 'cancelled'}:
            return status
    return 'completed'


def record_prepare_plan(task_id, role, tool_id, count):
    """Record only actual prepare completion, independently of stdout/sink success.

    First successful record wins. No historical replay, media, or list contents.
    The private console directory is the only authority; no shared-root fallback.
    """
    directory = None
    temporary = None
    try:
        expected = {'transcription': 'speech.prepare_audio',
                    'translation': 'text.prepare_batches'}.get(role)
        task_console._identity(task_id)
        root = console_root()
        if not root or expected is None or tool_id != expected:
            return
        if type(count) is not int or not 0 <= count < 2**31:
            return
        raw = json.dumps({'version': 1, 'task_id': task_id, 'role': role,
                          'tool_id': tool_id, 'planned_segments': count},
                         separators=(',', ':')).encode('utf8')
        if len(raw) > 1024:
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open('/', flags)
        parts = Path(os.path.abspath(root)).parts[1:]
        for number, part in enumerate(parts):
            if number == len(parts) - 1:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        import uuid
        temporary = '.' + uuid.uuid4().hex + '.progress.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        # Exclusive publication is atomic and cannot follow/overwrite a symlink.
        os.link(temporary, task_id + '.progress.json',
                src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    except Exception:
        pass
    finally:
        if directory is not None:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
            try:
                os.close(directory)
            except OSError:
                pass


def invoke_observed(tool, source, *, task_id, role, identity, index):
    with task_capture(task_id):
        started = time.monotonic()
        emit('mideagent.tool.v1', role, 'started', tool_id=identity, index=index)
        try:
            result = tool.invoke({'source': source})
        except BaseException as error:
            emit('mideagent.tool.v1', role, 'failed', tool_id=identity, index=index,
                 started=started, error=error, error_code='tool_exception')
            raise
        planned = (len(result) if identity in {'speech.prepare_audio', 'text.prepare_batches'}
                   and type(result) is list else None)
        if planned is not None:
            record_prepare_plan(task_id, role, identity, planned)
        emit('mideagent.tool.v1', role, result_state(result), tool_id=identity,
             index=index, started=started, planned_segments=planned)
        return result
