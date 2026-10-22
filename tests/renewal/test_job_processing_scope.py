"""Scope-only regressions. Real disposable PG; controlled attempt records.

No operating job, broker message, native target, or browser video journey.
"""

from uuid import uuid4
import pytest
from test_job_processing_review import (
    db as db,
    admin as admin,
    movie as movie,
    runtime as runtime,
    setup,
    graph,
    admit,
    original_rows,
)
from video_service.postgres import Conflict
from video_service.postgres.job_processing_review import JobProcessingReview


def reviewable(runtime, owner, movie, definition=None, *, remote=False):
    _, _, job = setup(runtime, owner, movie, definition or graph("encode"))
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, command)
    with runtime.database.connection() as c:
        c.execute(
            "UPDATE node_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (command["attempt_id"],),
        )
    runtime.get(owner, job["id"])
    if remote:
        from video_service.postgres.remote_control import RemoteControl
        from video_service.postgres.worker_telemetry import WorkerTelemetry
        from video_service.worker_telemetry import exchange

        # Controlled remote-reference/report metadata, not an actual MQ worker.
        outputs = runtime._import_outputs(owner, command, result)
        runtime.store.storage_kind = "s3"
        result = {**result, "transport": "s3_subprocess", "outputs": outputs}
        worker, boot = uuid4().hex, uuid4().hex
        control = RemoteControl(runtime.database)
        control.provision("encode", "a" * 64, [worker])
        control.publish(
            "encode",
            "a" * 64,
            [
                {
                    "id": worker,
                    "boot_id": boot,
                    "running": True,
                    "state": "ready",
                    "started_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        with runtime.database.connection() as c:
            c.execute(
                "INSERT INTO broker_dispatch_queue(owner_id,job_id,node_run_id,agent_id,phase,worker_id,boot_id) VALUES(%s,%s,%s,'encode','completed',%s,%s)",
                (owner, job["id"], command["attempt_id"], worker, boot),
            )
        reports = WorkerTelemetry(runtime.database)
        frame = {
            "version": 1,
            "worker_id": worker,
            "boot_id": boot,
            "family": "cpu",
            "role": "encode",
            "state": "busy",
            "sequence": 1,
            "ticket_id": job["id"],
            "attempt_id": command["attempt_id"],
        }
        reports.accept(frame, exchange("cpu", "encode"), expected_worker_id=worker)
        reports.accept(
            {
                **frame,
                "sequence": 2,
                "state": "ready",
                "ticket_id": None,
                "attempt_id": None,
            },
            exchange("cpu", "encode"),
            expected_worker_id=worker,
        )
    runtime.accept(owner, command, result)
    return JobProcessingReview(runtime), job, command


def assert_no_recovery(runtime, owner, job, review, plan):
    before = original_rows(runtime, job["id"])
    with runtime.database.connection() as c:
        queue_before = c.execute(
            "SELECT * FROM broker_dispatch_queue WHERE owner_id=%s AND job_id=%s ORDER BY node_run_id",
            (owner, job["id"]),
        ).fetchall()
    with pytest.raises(Conflict):
        review.decide(
            owner,
            job["id"],
            plan_id=plan["plan_id"],
            decision_id=uuid4().hex,
            choice="create_child",
            reason="scope negative test",
            acknowledge_duplicate_risk=True,
        )
    assert original_rows(runtime, job["id"]) == before
    with runtime.database.connection() as c:
        assert (
            c.execute(
                "SELECT * FROM broker_dispatch_queue WHERE owner_id=%s AND job_id=%s ORDER BY node_run_id",
                (owner, job["id"]),
            ).fetchall()
            == queue_before
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM jobs WHERE parent_id=%s", (job["id"],)
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM job_processing_decisions WHERE owner_id=%s",
                (owner,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM broker_dispatch_queue WHERE owner_id=%s AND job_id=%s AND release_decision_id IS NOT NULL",
                (owner, job["id"]),
            ).fetchone()["n"]
            == 0
        )


def test_two_encode_nodes_are_out_of_scope_even_with_one_verified_terminal_receipt(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    review, job, _ = reviewable(runtime, owner, movie, graph("encode", "encode"))
    plan = review.preview(owner, job["id"])
    assert not plan["can_create_child"]
    assert "single_encode_scope_required" in plan["hold_reasons"]
    assert_no_recovery(runtime, owner, job, review, plan)


def insert_sibling(runtime, owner, job, command, status, *, completed_result=False):
    from psycopg import sql
    from psycopg.types.json import Jsonb
    from video_service.cpu_agents import digest

    with runtime.database.connection() as c:
        row = dict(
            c.execute(
                "SELECT * FROM node_runs WHERE owner_id=%s AND job_id=%s AND id=%s",
                (owner, job["id"], command["attempt_id"]),
            ).fetchone()
        )
        sibling = uuid4().hex
        row.update(
            id=sibling, attempt=2, status=status, result=completed_result or None
        )
        row["lease_expires_at"] = (
            c.execute("SELECT now()+interval '5 minutes' AS expiry").fetchone()[
                "expiry"
            ]
            if status == "running"
            else None
        )
        if status == "completed":
            row["lease_owner"] = None
        row["request"] = {**row["request"], "attempt_id": sibling, "attempt": 2}
        row["request_sha256"] = digest(row["request"])
        columns = list(row)
        statement = sql.SQL("INSERT INTO node_runs ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
        )
        c.execute(
            statement,
            [
                Jsonb(row[k]) if isinstance(row[k], (dict, list)) else row[k]
                for k in columns
            ],
        )
    return sibling


@pytest.mark.parametrize(
    "status",
    [
        "waiting",
        "running",
        "review_required",
        "quarantined",
        "failed",
        "cancelled",
        "completed",
    ],
)
def test_other_nonterminal_or_unproven_attempt_blocks_child(
    runtime, admin, movie, status
):
    owner = admin[0]["id"]
    review, job, command = reviewable(runtime, owner, movie)
    assert review.preview(owner, job["id"])["can_create_child"]
    insert_sibling(runtime, owner, job, command, status)
    plan = review.preview(owner, job["id"])
    assert not plan["can_create_child"]
    assert "other_attempt_outcome_unconfirmed" in plan["hold_reasons"]
    assert_no_recovery(runtime, owner, job, review, plan)


def test_other_attempt_inserted_after_preview_rejects_old_judgment(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    review, job, command = reviewable(runtime, owner, movie)
    plan = review.preview(owner, job["id"])
    assert plan["can_create_child"]
    insert_sibling(runtime, owner, job, command, "running")
    assert_no_recovery(runtime, owner, job, review, plan)


@pytest.mark.parametrize("phase", ["pending", "sending", "sent", "received", "unknown"])
def test_other_live_or_unknown_dispatch_blocks_even_if_its_run_says_completed(
    runtime, admin, movie, phase
):
    owner = admin[0]["id"]
    review, job, command = reviewable(runtime, owner, movie, remote=True)
    initial = review.preview(owner, job["id"])
    assert initial["can_create_child"]
    known = {
        "status": "completed",
        "outputs": initial["evidence"]["quarantined_results"][0]["outputs"],
    }
    sibling = insert_sibling(
        runtime, owner, job, command, "completed", completed_result=known
    )
    with runtime.database.connection() as c:
        c.execute(
            "INSERT INTO broker_dispatch_queue(owner_id,job_id,node_run_id,agent_id,phase) VALUES(%s,%s,%s,%s,%s)",
            (owner, job["id"], sibling, "encode", phase),
        )
    plan = review.preview(owner, job["id"])
    assert not plan["can_create_child"]
    assert "other_attempt_outcome_unconfirmed" in plan["hold_reasons"]
    assert_no_recovery(runtime, owner, job, review, plan)


def test_known_completed_sibling_does_not_get_misclassified_as_unresolved(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    review, job, command = reviewable(runtime, owner, movie)
    before = review.preview(owner, job["id"])
    assert before["can_create_child"]
    known = {
        "status": "completed",
        "outputs": before["evidence"]["quarantined_results"][0]["outputs"],
    }
    insert_sibling(runtime, owner, job, command, "completed", completed_result=known)
    assert review.preview(owner, job["id"])["can_create_child"]
    assert_no_recovery(runtime, owner, job, review, before)


def test_other_jobs_attempt_does_not_block_this_job(runtime, admin, movie):
    owner = admin[0]["id"]
    review, job, _ = reviewable(runtime, owner, movie)
    _, _, other = setup(runtime, owner, movie, graph("encode"))
    admit(runtime, owner, other["id"])
    runtime.claim_next(owner, other["id"])
    assert review.preview(owner, job["id"])["can_create_child"]
