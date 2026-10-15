"""Bounded admission waits for synchronous API endpoints, never worker execution."""
from contextlib import contextmanager, ExitStack
import time

from video_service.locking import job_lock, JobBusyError


@contextmanager
def admission_lock(repository, job_id='0' * 32, *, timeout=5):
    deadline = time.monotonic() + timeout
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(job_lock(repository, job_id))
                break
            except JobBusyError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(.05, remaining))
        # Do not catch/replay failures from the protected operation.
        yield
