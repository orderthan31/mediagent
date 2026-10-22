"""Disposable PG + real synthetic FFmpeg; never touches operating #5."""

from uuid import uuid4
import pytest
from test_execution import (
    db as db,
    admin as admin,
    movie as movie,
    runtime as runtime,
    setup,
    admit,
    graph,
)


def uncertain(runtime, owner, movie, *, execute=False):
    source, definition, job = setup(runtime, owner, movie, graph("encode"))
    admit(runtime, owner, job["id"])
    command = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, command) if execute else None
    with runtime.database.connection() as c:
        c.execute(
            "UPDATE node_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (command["attempt_id"],),
        )
        c.execute(
            "UPDATE message_outbox SET published_at=now() WHERE id=%s",
            (command["attempt_id"],),
        )
    return job, command, result


def original_rows(runtime, job):
    with runtime.database.connection() as c:
        return {
            "job": dict(c.execute("SELECT * FROM jobs WHERE id=%s", (job,)).fetchone()),
            "runs": [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM node_runs WHERE job_id=%s ORDER BY id", (job,)
                ).fetchall()
            ],
            "outbox": [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM message_outbox WHERE aggregate_id=%s ORDER BY id",
                    (job,),
                ).fetchall()
            ],
        }


def test_expired_legacy_attempt_gets_a_durable_case_not_a_fake_running_badge(
    runtime, admin, movie
):
    owner = admin[0]["id"]
    job, command, _ = uncertain(runtime, owner, movie)
    before = original_rows(runtime, job["id"])
    state = runtime.get(owner, job["id"])
    assert (state.get("processing_review") or {}).get("state") == "needs_review"
    assert state["status"] == "running"
    assert original_rows(runtime, job["id"]) == before
    from video_service.postgres.execution import Execution

    reopened = Execution(runtime.database, runtime.store).get(owner, job["id"])
    assert (
        reopened["processing_review"]["case_id"]
        == state["processing_review"]["case_id"]
    )
    assert runtime.claim_next(owner, job["id"]) is None


def test_admin_hold_is_reasoned_idempotent_and_fences_the_original(
    runtime, admin, movie
):
    from video_service.postgres.job_processing_review import JobProcessingReview
    from video_service.postgres import Conflict

    owner = admin[0]["id"]
    job, command, _ = uncertain(runtime, owner, movie)
    runtime.get(owner, job["id"])
    before = original_rows(runtime, job["id"])
    review = JobProcessingReview(runtime)
    plan = review.preview(owner, job["id"])
    assert not plan["can_create_child"]
    decision = uuid4().hex
    held = review.decide(
        owner,
        job["id"],
        plan_id=plan["plan_id"],
        decision_id=decision,
        choice="hold",
        reason="전달 근거가 부족해서 보류",
        acknowledge_duplicate_risk=False,
    )
    assert held["case"]["state"] == "held"
    repeated = review.decide(
        owner,
        job["id"],
        plan_id=plan["plan_id"],
        decision_id=decision,
        choice="hold",
        reason="전달 근거가 부족해서 보류",
        acknowledge_duplicate_risk=False,
    )
    assert len(repeated["history"]) == 1
    with pytest.raises(Conflict):
        review.decide(
            owner,
            job["id"],
            plan_id=plan["plan_id"],
            decision_id=uuid4().hex,
            choice="hold",
            reason="오래된 판단",
            acknowledge_duplicate_risk=False,
        )
    assert original_rows(runtime, job["id"]) == before
    with pytest.raises(Conflict):
        runtime.execute_command(owner, command)


def test_verified_late_output_is_quarantined_then_a_new_child_needs_its_own_admission(
    runtime, admin, movie
):
    from video_service.postgres.job_processing_review import JobProcessingReview

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    runtime.get(owner, job["id"])
    before = original_rows(runtime, job["id"])
    review = JobProcessingReview(runtime)
    assert not review.preview(owner, job["id"])["can_create_child"]
    runtime.accept(owner, command, result)
    assert original_rows(runtime, job["id"]) == before
    plan = review.preview(owner, job["id"])
    assert plan["can_create_child"]
    created = review.decide(
        owner,
        job["id"],
        plan_id=plan["plan_id"],
        decision_id=uuid4().hex,
        choice="create_child",
        reason="완료 근거를 격리 보존하고 새 승인으로 분리",
        acknowledge_duplicate_risk=True,
    )
    child = created["child"]
    assert created["history"][0]["acknowledge_duplicate_risk"] is True
    assert created["history"][0]["authority_snapshot"] == {
        "id": owner,
        "role": "admin",
        "active": True,
    }
    assert (
        created["history"][0]["plan_context"]["policy"] == "encode-terminal-receipt-v1"
    )
    assert (
        child["parent_id"] == job["id"]
        and child["status"] == "draft"
        and child["active_claim_id"] is None
    )
    assert (
        child["snapshot"]["inputs"]
        == runtime.get(owner, job["id"])["snapshot"]["inputs"]
    )
    assert runtime.run_local(owner, child["id"])["status"] == "draft"
    admit(runtime, owner, child["id"])
    done = runtime.run_local(owner, child["id"])
    assert done["status"] == "completed"
    assert done["runs"][0]["id"] != command["attempt_id"]
    runtime.accept(owner, command, result)
    assert original_rows(runtime, job["id"]) == before
    with runtime.database.connection() as c:
        assert (
            c.execute("SELECT count(*) n FROM job_processing_late_results").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM artifacts WHERE job_id=%s", (job["id"],)
            ).fetchone()["n"]
            == 0
        )


def test_admin_routes_require_auth_csrf_and_recheck_role(runtime, admin, movie):
    from fastapi.testclient import TestClient
    from test_foundation import login
    from app.renewal import create_app

    owner = admin[0]["id"]
    job, _, _ = uncertain(runtime, owner, movie)
    runtime.get(owner, job["id"])
    app = create_app(
        runtime.database,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
        local_execution=True,
    )
    base = "/api/admin/jobs/" + job["id"] + "/processing-review"
    with TestClient(app) as client:
        assert client.get(base).status_code == 401
        login(client, admin)
        assert client.get(base).status_code == 200
        csrf = client.headers.pop("X-CSRF-Token")
        assert client.post(base + "/preview", json={}).status_code == 403
        client.headers["X-CSRF-Token"] = csrf
        client.headers["Origin"] = "http://testserver"
        plan = client.post(base + "/preview", json={})
        assert plan.status_code == 200
        body = {
            "plan_id": plan.json()["plan_id"],
            "decision_id": uuid4().hex,
            "choice": "hold",
            "reason": "검증 보류",
            "acknowledge_duplicate_risk": False,
        }
        assert client.post(base + "/decisions", json=body).status_code == 200
        with runtime.database.connection() as c:
            c.execute("UPDATE accounts SET role='user' WHERE id=%s", (owner,))
        assert client.get(base).status_code == 403


def test_reviewed_sources_are_database_fenced_and_late_results_do_not_override_child(
    runtime, admin, movie
):
    import psycopg

    owner = admin[0]["id"]
    job, command, _ = uncertain(runtime, owner, movie)
    runtime.get(owner, job["id"])
    before = original_rows(runtime, job["id"])
    statements = [
        ("UPDATE jobs SET status='failed' WHERE id=%s", job["id"]),
        ("UPDATE node_runs SET status='failed' WHERE id=%s", command["attempt_id"]),
        (
            "UPDATE message_outbox SET published_at=NULL WHERE id=%s",
            command["attempt_id"],
        ),
    ]
    for sql, value in statements:
        with pytest.raises(psycopg.Error):
            with runtime.database.connection() as c:
                c.execute(sql, (value,))
    assert original_rows(runtime, job["id"]) == before


def test_observation_change_invalidates_plan_and_concurrent_child_creation_is_single(
    runtime, admin, movie
):
    from concurrent.futures import ThreadPoolExecutor
    from video_service.postgres.job_processing_review import JobProcessingReview
    from video_service.postgres import Conflict

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    review = JobProcessingReview(runtime)
    runtime.get(owner, job["id"])
    old = review.preview(owner, job["id"])
    runtime.accept(owner, command, result)
    with pytest.raises(Conflict):
        review.decide(
            owner,
            job["id"],
            plan_id=old["plan_id"],
            decision_id=uuid4().hex,
            choice="hold",
            reason="오래된 관측",
            acknowledge_duplicate_risk=False,
        )
    plan = review.preview(owner, job["id"])

    def create(_):
        try:
            return review.decide(
                owner,
                job["id"],
                plan_id=plan["plan_id"],
                decision_id=uuid4().hex,
                choice="create_child",
                reason="검증된 종료 근거",
                acknowledge_duplicate_risk=True,
            )["child"]["id"]
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        children = list(pool.map(create, range(2)))
    assert len([v for v in children if v]) == 1
    with runtime.database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) n FROM jobs WHERE parent_id=%s", (job["id"],)
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute("SELECT count(*) n FROM job_processing_decisions").fetchone()["n"]
            == 1
        )


def test_unverified_or_changed_quarantine_cannot_authorize_recovery(
    runtime, admin, movie
):
    from video_service.postgres.job_processing_review import JobProcessingReview
    from video_service.postgres import Conflict

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    runtime.get(owner, job["id"])
    runtime.accept(owner, command, result)
    review = JobProcessingReview(runtime)
    good = review.preview(owner, job["id"])
    assert good["can_create_child"]
    ref = good["evidence"]["quarantined_results"][0]["outputs"]["video"]
    path = runtime.store.path(owner, ref)
    path.chmod(0o600)
    path.write_bytes(b"isolated-corruption")
    plan = review.preview(owner, job["id"])
    assert not plan["can_create_child"]
    with pytest.raises(Conflict):
        review.decide(
            owner,
            job["id"],
            plan_id=good["plan_id"],
            decision_id=uuid4().hex,
            choice="create_child",
            reason="변경된 파일",
            acknowledge_duplicate_risk=True,
        )


def test_unknown_dispatch_requires_bound_receive_and_keeps_original_phase_after_review(
    runtime, admin, movie
):
    from video_service.postgres.job_processing_review import JobProcessingReview
    from video_service.postgres.remote_control import RemoteControl
    from video_service.postgres.worker_telemetry import WorkerTelemetry
    from video_service.worker_telemetry import exchange

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    outputs = runtime._import_outputs(owner, command, result)
    # Controlled object-store/status adapter seam, real generated media bytes.
    runtime.store.storage_kind = "s3"
    remote = {**result, "transport": "s3_subprocess", "outputs": outputs}
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
            "INSERT INTO broker_dispatch_queue(owner_id,job_id,node_run_id,agent_id,phase,worker_id,boot_id) VALUES(%s,%s,%s,'encode','unknown',%s,%s)",
            (owner, job["id"], command["attempt_id"], worker, boot),
        )
        c.execute(
            "UPDATE message_outbox SET published_at=NULL WHERE id=%s",
            (command["attempt_id"],),
        )
        c.execute(
            "UPDATE node_runs SET status='waiting' WHERE id=%s",
            (command["attempt_id"],),
        )
        c.execute("UPDATE jobs SET status='waiting' WHERE id=%s", (job["id"],))
    runtime.get(owner, job["id"])
    runtime.accept(owner, command, remote)
    review = JobProcessingReview(runtime)
    assert not review.preview(owner, job["id"])["can_create_child"]
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
    plan = review.preview(owner, job["id"])
    assert plan["can_create_child"]
    decision = uuid4().hex
    state = review.decide(
        owner,
        job["id"],
        plan_id=plan["plan_id"],
        decision_id=decision,
        choice="create_child",
        reason="수신·종료·정상대기 및 격리 파일 검증",
        acknowledge_duplicate_risk=True,
    )
    assert state["child"]["status"] == "draft"
    with runtime.database.connection() as c:
        q = c.execute(
            "SELECT phase,published_at,release_decision_id FROM broker_dispatch_queue WHERE node_run_id=%s",
            (command["attempt_id"],),
        ).fetchone()
        assert (
            q["phase"] == "unknown"
            and q["published_at"] is None
            and q["release_decision_id"] == decision
        )
    from video_service.durable_transport import DurableTransport

    sent = []
    assert (
        DurableTransport(runtime).publish_exact(
            owner, job["id"], command["attempt_id"], lambda *args: sent.append(args)
        )
        is False
    )
    assert sent == []
    # Only the reviewed reservation is excluded, without resetting its phase.
    from test_dispatch_queue import Publisher
    from video_service.rabbitmq_controller import BrokerController

    with runtime.database.connection() as c:
        c.execute(
            "UPDATE remote_control_groups SET enabled=true,replicas=1 WHERE agent_id='encode'"
        )
    publisher = Publisher()
    controller = BrokerController(runtime, publisher)
    admit(runtime, owner, state["child"]["id"])
    dispatched = controller.dispatch(owner, state["child"]["id"])
    assert (
        len(publisher.sent) == 1
        and dispatched["runs"][0]["dispatch"]["phase"] == "sent"
    )


def test_active_sender_and_missing_risk_ack_keep_recovery_blocked(
    runtime, admin, movie
):
    from video_service.postgres.job_processing_review import JobProcessingReview
    from video_service.postgres.dispatch_queue import DispatchQueue
    from video_service.postgres import Conflict

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    runtime.get(owner, job["id"])
    runtime.accept(owner, command, result)
    review = JobProcessingReview(runtime)
    with runtime.database.connection() as sender:
        assert DispatchQueue._try_guard_in(sender, "encode", session=True)
        blocked = review.preview(owner, job["id"])
        assert (
            not blocked["can_create_child"]
            and "sender_still_active" in blocked["hold_reasons"]
        )
    plan = review.preview(owner, job["id"])
    assert plan["can_create_child"]
    with pytest.raises(Conflict):
        review.decide(
            owner,
            job["id"],
            plan_id=plan["plan_id"],
            decision_id=uuid4().hex,
            choice="create_child",
            reason="동의 미제출",
            acknowledge_duplicate_risk=False,
        )
    with pytest.raises(ValueError):
        review.decide(
            owner,
            job["id"],
            plan_id=plan["plan_id"],
            decision_id=uuid4().hex,
            choice="hold",
            reason="  ",
            acknowledge_duplicate_risk=False,
        )
    with runtime.database.connection() as c:
        assert (
            c.execute("SELECT count(*) n FROM job_processing_decisions").fetchone()["n"]
            == 0
        )


def test_failed_unknown_cannot_bypass_review_via_the_old_recover_route(
    runtime, admin, movie
):
    from video_service.postgres.remote_control import RemoteControl
    from video_service.postgres import Conflict

    owner = admin[0]["id"]
    job, command, _ = uncertain(runtime, owner, movie)
    RemoteControl(runtime.database).provision("encode", "a" * 64, [uuid4().hex])
    with runtime.database.connection() as c:
        c.execute(
            "INSERT INTO broker_dispatch_queue(owner_id,job_id,node_run_id,agent_id,phase) VALUES(%s,%s,%s,'encode','unknown')",
            (owner, job["id"], command["attempt_id"]),
        )
        c.execute("UPDATE jobs SET status='failed' WHERE id=%s", (job["id"],))
        c.execute(
            "UPDATE node_runs SET status='quarantined' WHERE id=%s",
            (command["attempt_id"],),
        )
    state = runtime.get(owner, job["id"])
    assert state["processing_review"]["cause"] == "dispatch_unknown"
    with pytest.raises(Conflict):
        runtime.recover(owner, job["id"], uuid4().hex, acknowledge_duplicate_risk=True)


def test_quarantined_download_is_real_scoped_media_with_a_usable_extension(
    runtime, admin, movie
):
    import hashlib
    from fastapi.testclient import TestClient
    from test_foundation import login
    from app.renewal import create_app
    from video_service.postgres.job_processing_review import JobProcessingReview

    owner = admin[0]["id"]
    job, command, result = uncertain(runtime, owner, movie, execute=True)
    runtime.get(owner, job["id"])
    runtime.accept(owner, command, result)
    state = JobProcessingReview(runtime).status(owner, job["id"])
    receipt = state["evidence"]["quarantined_results"][0]
    ref = receipt["outputs"]["video"]
    app = create_app(
        runtime.database,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
        local_execution=True,
    )
    with TestClient(app) as client:
        endpoint = (
            "/api/admin/jobs/"
            + job["id"]
            + "/processing-review/quarantine/"
            + receipt["message_sha256"]
            + "/video"
        )
        assert client.get(endpoint).status_code == 401
        login(client, admin)
        response = client.get(endpoint)
        assert response.status_code == 200
        assert (
            hashlib.sha256(response.content).hexdigest() == ref["sha256"]
            and len(response.content) == ref["bytes"]
        )
        assert ".mp4" in response.headers["content-disposition"]
        assert client.get(endpoint.replace(job["id"], "0" * 32)).status_code == 404


def test_legacy_lease_classification_uses_database_clock_not_api_host_clock(
    runtime, admin, movie, monkeypatch
):
    from datetime import datetime, timezone
    import video_service.postgres.job_processing_review as module

    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, graph("encode"))
    admit(runtime, owner, job["id"])
    runtime.claim_next(owner, job["id"])

    class AheadClock:
        @staticmethod
        def now(_):
            return datetime(2099, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(module, "datetime", AheadClock, raising=False)
    assert runtime.get(owner, job["id"]).get("processing_review") is None
