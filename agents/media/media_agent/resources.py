"""Per-stage, cross-process limits with cancellation and visible wait reasons."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import os
import time
from video_service.locking import _file_lock, job_lock, JobBusyError
from video_service.models import utc_now_iso

_context = ContextVar('job_resource_context', default=None)
_held = ContextVar('held_job_resources', default=frozenset())
LIMITS = {'gpu': ('MAX_GPU_JOBS', 1), 'io': ('MAX_IO_JOBS', 2), 'llm': ('MAX_LLM_JOBS', 1)}
LABELS = {'gpu': 'GPU 사용 대기', 'io': '영상·파일 처리 대기', 'llm': '전사·번역 요청 대기'}


@contextmanager
def job_resources(repo, job_id):
    token = _context.set((repo, job_id))
    try:
        yield
    finally:
        _context.reset(token)


def waiting(resource, started, *, finished=False):
    context = _context.get()
    if context is None:
        return
    repo, job_id = context
    if job_id is None:
        return
    try:
        with job_lock(repo, job_id):
            record = repo.read(job_id)
            if finished:
                record.metadata['resource_wait_seconds'] = round(
                    record.metadata.get('resource_wait_seconds', 0) + time.monotonic() - started, 3)
                record.metadata.update(wait_reason=None, wait_started_at=None)
            else:
                record.metadata['wait_reason'] = LABELS[resource]
                record.metadata.setdefault('wait_started_at', utc_now_iso())
                if record.metadata['wait_started_at'] is None:
                    record.metadata['wait_started_at'] = utc_now_iso()
            repo.save(record)
    except JobBusyError:
        pass


@contextmanager
def resource_slot(resource, check=lambda: None):
    context = _context.get()
    if context is None or resource in _held.get():
        yield
        return
    repo, _ = context
    name, default = LIMITS[resource]
    limit = int(os.getenv(name, str(default)))
    if not 1 <= limit <= 16:
        raise ValueError(f'{name} must be between 1 and 16')
    directory = repo.storage_root / '.locks'
    directory.mkdir(exist_ok=True)
    start, announced, last = time.monotonic(), False, 0
    with ExitStack() as stack:
        try:
            while True:
                check()
                acquired = False
                for index in range(limit):
                    try:
                        stack.enter_context(_file_lock(directory / f'resource-{resource}-{index}.lock'))
                        acquired = True
                        break
                    except JobBusyError:
                        continue
                if acquired:
                    break
                if time.monotonic() - last >= 1:
                    waiting(resource, start)
                    announced, last = True, time.monotonic()
                time.sleep(.1)
        finally:
            if announced:
                waiting(resource, start, finished=True)
        token = _held.set(_held.get() | {resource})
        try:
            check()
            yield
        finally:
            _held.reset(token)


def limited(resource):
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            check = kwargs.get('check', lambda: None)
            with resource_slot(resource, check):
                return function(*args, **kwargs)
        return invoke
    return decorate


@contextmanager
def gpu_slot(check=lambda: None, *, keep_preview=False):
    with resource_slot('gpu', check):
        if not keep_preview and _context.get() is not None:
            from .faceswap.warm import release
            release()
        yield
