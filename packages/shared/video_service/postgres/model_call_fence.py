"""Product job cancellation versus new external model-call admission.

Shared session locks preserve chunk parallelism and span actual adapter entry/I/O.
Cancellation takes the exclusive transaction lock BEFORE its job row lock. Never
hold a job/run row transaction across provider or publisher network operations.
"""

from contextlib import contextmanager


def key(owner, job_id):
    return "model-call-fence:" + owner + ":" + job_id


@contextmanager
def model_call_fence(database, owner, job_id):
    # Separate non-pooled connection: session ownership spans transaction commits.
    with database.connection() as c:
        value = key(owner, job_id)
        c.execute("SELECT pg_advisory_lock_shared(hashtextextended(%s,0))", (value,))
        c.commit()
        try:
            yield
        finally:
            c.rollback()
            c.execute(
                "SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))", (value,)
            )
            c.commit()


def lock_product_cancel(connection, owner, job_id):
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key(owner, job_id),)
    )
