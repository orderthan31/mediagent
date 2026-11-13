"""Isolated PG admission checks; real CPU receipts, no model/provider execution."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_execution import admin as _admin, db as _db, movie as _movie, admit
from test_agent_control_workflow import node, edge, graph
from test_model_role_orchestration import formal
from mideagent_orchestrator.agent_pool import AgentPool
from video_service.model_role_coordinator import ModelRoleCoordinator

admin, db, movie = _admin, _db, _movie


def prepared(db, admin, movie, tmp_path, *, enrolled=True, enabled=True):
    runtime, owner, legacy = formal(db, admin, movie, tmp_path, prepare=False)
    model = next(n["model_ref"] for n in legacy["snapshot"]["definition"]["nodes"] if n["type"] == "transcribe")
    speech = {**node("speech", "transcription_agent"), "model_ref": model}
    public = graph([speech, node("approval", "review", data_type="transcript")],
                   [edge("speech", "transcript", "approval", "value")])
    saved = runtime.save_definition(owner, uuid4().hex, public)
    job = runtime.create(owner, legacy["asset_id"], saved["id"], saved["revision"], request_id=uuid4().hex)
    assert job["snapshot"]["agent_control_policy"] == 1
    published = []

    @contextmanager
    def role_factory():
        yield SimpleNamespace(publish_command=lambda packet: published.append(packet) or True)

    coordinator = ModelRoleCoordinator(runtime, SimpleNamespace(model_role_factory=role_factory))
    coordinator.auto_enroll_new_job(owner, job["id"], uuid4().hex)
    assert coordinator.enrolled(runtime, owner, job["id"])
    with db.connection() as conn:
        conn.execute("INSERT INTO agent_pool_roles(role,max_instances,memory_bytes,idle_seconds,template_sha256,enabled) VALUES ('transcription',1,512,30,%s,%s)", ("a" * 64, enabled))
    admit(runtime, owner, job["id"])
    # New Start claims enroll in the pool during their first native claim.
    for expected in ("analyze", "extract_audio", "preprocess_audio"):
        command = runtime.claim_next(owner, job["id"])
        assert command["agent"]["id"] == expected
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed" and result["transport"] == "subprocess"
        runtime.accept(owner, command, result)
    with db.connection() as conn:
        if not enrolled:
            # Fixture for an already-started historical/local job, not a new Start.
            conn.execute("DELETE FROM agent_pool_jobs WHERE job_id=%s", (job["id"],))
        raw = runtime._job(conn, owner, job["id"])
        assert AgentPool.enrolled_in(conn, raw) == enrolled
    return runtime, owner, job, coordinator, published


def demands(db, job):
    with db.connection() as conn:
        return conn.execute("SELECT * FROM agent_pool_demands WHERE job_id=%s", (job["id"],)).fetchall()


def model_counts(db, job):
    with db.connection() as conn:
        return tuple(conn.execute(query, (job["id"],)).fetchone()["n"] for query in (
            "SELECT count(*) n FROM node_runs WHERE job_id=%s AND node_type='transcribe'",
            "SELECT count(*) n FROM model_role_tasks WHERE job_id=%s",
            "SELECT count(*) n FROM message_outbox WHERE aggregate_id=%s AND payload->'agent'->>'id'='transcribe'",
        ))


@pytest.mark.parametrize("observation", ["absent", "starting", "busy", "stale", "other_role"])
def test_native_control_cold_pool_queues_without_model_attempt(db, admin, movie, tmp_path, observation):
    runtime, owner, job, coordinator, published = prepared(db, admin, movie, tmp_path)
    with db.connection() as conn:
        if observation != "absent":
            role = "translation" if observation == "other_role" else "transcription"
            if role == "translation":
                conn.execute("INSERT INTO agent_pool_roles SELECT 'translation',max_instances,memory_bytes,idle_seconds,template_sha256,enabled FROM agent_pool_roles WHERE role='transcription'")
            conn.execute("INSERT INTO agent_pool_instances(id,role,slot,template_sha256,phase,observed_at) VALUES (%s,%s,0,%s,%s,now() - %s * interval '1 second')",
                         (uuid4().hex, role, "a" * 64, observation if observation in {"starting", "busy"} else "ready", 10 if observation == "stale" else 0))
    for _ in range(2):
        command = runtime.claim_next(owner, job["id"])
        assert command is None, "cold pool must not admit a model command"
    pending = demands(db, job)
    assert len(pending) == 1
    assert pending[0]["node_id"] == "speech__transcribe"
    assert pending[0]["role"] == "transcription" and pending[0]["node_run_id"] is None
    assert model_counts(db, job) == (0, 0, 0)
    assert not published
    state = runtime.get(owner, job["id"])
    assert state["execution_state"] == "preparing"
    assert state["snapshot"] == job["snapshot"]
    assert state["snapshot_sha256"] == job["snapshot_sha256"]
    assert all(run["status"] == "completed" for run in state["runs"])

    # Test-only observation of a compatible ready worker; no worker/provider is run.
    with db.connection() as conn:
        conn.execute("INSERT INTO agent_pool_instances(id,role,slot,template_sha256,phase,observed_at) VALUES (%s,'transcription',0,%s,'ready',now()) ON CONFLICT (role,slot) WHERE phase<>'removed' DO UPDATE SET phase='ready',observed_at=now()", (uuid4().hex, "a" * 64))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = list(pool.map(lambda _: runtime.claim_next(owner, job["id"]), range(2)))
    commands = [command for command in commands if command is not None]
    assert len(commands) == 1
    command = commands[0]
    assert command["agent"]["id"] == "transcribe"
    assert coordinator.publish(owner, command)
    assert runtime.claim_next(owner, job["id"]) is None
    assert model_counts(db, job) == (1, 1, 1)
    assert len(published) == 1
    assert len(demands(db, job)) == 1
    assert demands(db, job)[0]["node_run_id"] == command["attempt_id"]


@pytest.mark.parametrize("enrolled,enabled", [(False, True), (True, False)])
def test_unenrolled_or_disabled_pool_preserves_admission(db, admin, movie, tmp_path, enrolled, enabled):
    runtime, owner, job, coordinator, published = prepared(db, admin, movie, tmp_path, enrolled=enrolled, enabled=enabled)
    command = runtime.claim_next(owner, job["id"])
    assert command["agent"]["id"] == "transcribe"
    assert coordinator.publish(owner, command)
    assert len(published) == 1 and not demands(db, job)
    assert model_counts(db, job) == (1, 1, 1)


def test_cancelled_queued_demand_cannot_resume_when_capacity_appears(db, admin, movie, tmp_path):
    runtime, owner, job, _coordinator, published = prepared(db, admin, movie, tmp_path)
    assert runtime.claim_next(owner, job["id"]) is None
    pending = demands(db, job)
    assert len(pending) == 1 and pending[0]["node_run_id"] is None
    state = runtime.get(owner, job["id"])
    runtime.cancel(owner, job["id"], state["revision"])
    with db.connection() as conn:
        conn.execute("INSERT INTO agent_pool_instances(id,role,slot,template_sha256,phase,observed_at) VALUES (%s,'transcription',0,%s,'ready',now())", (uuid4().hex, "a" * 64))
    assert runtime.claim_next(owner, job["id"]) is None
    cancelled = runtime.get(owner, job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["snapshot"] == job["snapshot"]
    assert cancelled["runs"] == state["runs"]
    assert demands(db, job) == pending
    assert model_counts(db, job) == (0, 0, 0) and not published
