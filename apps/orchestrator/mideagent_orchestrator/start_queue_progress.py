"""Explicit progression of already-authorized new Starts; never a broad job scan."""
from .start_queue import StartQueue
import logging


def advance_start_queue(runtime, owner, dispatch_exact):
    # Every dispatch still passes the authoritative, locked claim_next gate.
    # Once a first attempt commits, the next candidate can use another slot;
    # this does not wait for completion or replay active/unknown attempts.
    failures = 0
    try:
        jobs = StartQueue(runtime).progression(owner)
    except Exception as exc:
        # Progression of sibling new Starts cannot roll back an accepted result
        # or turn an unrelated durable result receipt into a model retry.
        logging.getLogger(__name__).warning('start_queue_read_unconfirmed: %s', type(exc).__name__)
        return False
    for job_id in jobs:
        try:
            dispatch_exact(owner, job_id)
        except Exception as exc:
            failures += 1
            logging.getLogger(__name__).warning('start_queue_progress_unconfirmed: %s', type(exc).__name__)
    return failures == 0


class StartQueuePump:
    """Small wakeups inside the existing API lifecycle; no daemon/service/stack.

    Only the dedicated policy namespace is enumerated, at most20 owners/tick.
    Its cursor is merely a traversal hint; every reservation rechecks S3+PG.
    """
    def __init__(self, runtime, dispatch_exact):
        self.runtime, self.dispatch_exact = runtime, dispatch_exact
        self.after = None

    def tick(self):
        try:
            owners, more = self.runtime.store.list_start_queue_owners(self.after)
        except Exception as exc:
            logging.getLogger(__name__).warning('start_queue_index_unconfirmed: %s', type(exc).__name__)
            return False
        confirmed = True
        for owner in owners:
            confirmed = advance_start_queue(self.runtime, owner, self.dispatch_exact) and confirmed
        self.after = owners[-1] if owners and more else None
        return confirmed
