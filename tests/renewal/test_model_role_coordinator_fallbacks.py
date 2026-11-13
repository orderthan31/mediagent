"""Coordinator unit tests: real imported coordinator, in-memory SQL boundary.

No PostgreSQL, queue, provider, model calls, or claim/publication integration.
"""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from mideagent_orchestrator.model_roles import ModelRoleCoordinator
from video_service.canonical import digest
from video_service.postgres import Conflict


def reference(index):
    return {"model_id": f"{index:032x}", "revision": 1}


class EnrollmentBoundary:
    def __init__(self, job):
        self.job = job
        self.rows = []
        self.attempts = 0

    def connection(self):
        return nullcontext(self)

    def execute(self, sql, params):
        row = None
        if sql.startswith("SELECT * FROM model_role_enrollments"):
            row = next((r for r in self.rows if r["request_id"] == params[1]), None)
        elif sql.startswith("SELECT 1 FROM model_role_enrollments"):
            row = next((r for r in self.rows if r["generation"] == params[2]), None)
        elif sql.startswith("SELECT count(*) n FROM node_runs"):
            row = {"n": self.attempts}
        elif sql.startswith("INSERT INTO model_role_enrollments"):
            self.rows.append(dict(zip(
                ("owner", "job_id", "generation", "snapshot_sha256", "request_id", "request_sha256", "response"),
                (*params[:-1], deepcopy(params[-1].obj)),
            )))
        elif sql.startswith("UPDATE jobs SET revision=revision+1"):
            self.job["revision"] += 1
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)


def setup_coordinator(*, version=2, width=2, cap="auto"):
    refs = [reference(i + 1) for i in range(width)]
    node = {"id": "asr", "type": "transcribe", "model_ref": refs[0],
            "fallback_refs": refs[1:], "options": {
                "clock_policy": "packed_projection_v5", "batch_policy": "bounded_60s_v1",
                "max_model_calls": cap}}
    snapshot = {"role_policy_version": version, "definition": {"nodes": [node]},
                "model_bindings": {"asr": {**refs[0], "fallbacks": deepcopy(refs[1:])}}}
    job = {"id": "job", "generation": 1, "revision": 3, "status": "draft", "runs": [],
           "cancel_requested": False, "active_claim_id": None,
           "snapshot": snapshot, "snapshot_sha256": digest(snapshot)}
    db = EnrollmentBoundary(job)

    def get(owner, job_id, **kwargs):
        assert owner == "owner" and job_id == "job"
        return deepcopy(job)

    runtime = SimpleNamespace(database=db, store=object(), get=get,
                              _job=lambda c, owner, job_id, **kw: get(owner, job_id))

    def no_transport():
        pytest.fail("enrollment must not publish or call a model")

    coordinator = ModelRoleCoordinator(runtime, SimpleNamespace(model_role_factory=no_transport))
    return coordinator, db, node


@pytest.mark.parametrize("cap", ["auto", "1", "128"])
@pytest.mark.parametrize("width", [1, 2, 4])
@pytest.mark.parametrize("automatic", [True, False])
def test_fresh_v2_configured_chain_enrolls_without_changing_snapshot(cap, width, automatic):
    coordinator, db, _ = setup_coordinator(cap=cap, width=width)
    before = deepcopy(db.job["snapshot"])
    if automatic:
        after = coordinator.auto_enroll_new_job("owner", "job", "request")
        assert after["status"] == "draft" and after["runs"] == []
    else:
        coordinator.enroll_job("owner", "job", 3, "request")
    assert len(db.rows) == 1
    assert db.rows[0]["snapshot_sha256"] == digest(before)
    assert db.rows[0]["generation"] == 1
    assert db.job["revision"] == 4
    assert db.job["snapshot"] == before
    coordinator.auto_enroll_new_job("owner", "job", "another-request")
    assert len(db.rows) == 1 and db.job["revision"] == 4


@pytest.mark.parametrize("version", [None, 1, "2", 2.0, True, 3])
def test_only_explicit_integer_v2_allows_fallbacks(version):
    coordinator, db, _ = setup_coordinator(version=version)
    coordinator.auto_enroll_new_job("owner", "job", "request")
    assert not db.rows
    with pytest.raises(Conflict, match="supported_frozen_transcription"):
        coordinator.enroll_job("owner", "job", 3, "request")


def test_legacy_single_model_still_enrolls():
    coordinator, db, _ = setup_coordinator(version=1, width=1)
    coordinator.auto_enroll_new_job("owner", "job", "request")
    assert len(db.rows) == 1


@pytest.mark.parametrize("change", ["clock", "batch", "too_many", "duplicate", "bad_revision",
                                    "bad_id", "not_list", "missing_primary", "missing_pin",
                                    "pin_revision", "pin_order", "extra_pin"])
def test_unsupported_or_unfrozen_chain_never_enrolls(change):
    coordinator, db, node = setup_coordinator(width=3)
    pin = db.job["snapshot"]["model_bindings"]["asr"]
    if change == "clock": node["options"]["clock_policy"] = "other"
    elif change == "batch": node["options"]["batch_policy"] = "other"
    elif change == "too_many": node["fallback_refs"] += [reference(4), reference(5)]
    elif change == "duplicate": node["fallback_refs"][0] = node["model_ref"]
    elif change == "bad_revision": node["fallback_refs"][0]["revision"] = True
    elif change == "bad_id": node["fallback_refs"][0]["model_id"] = "not-a-model"
    elif change == "not_list": node["fallback_refs"] = "bad"
    elif change == "missing_primary": del node["model_ref"]
    elif change == "missing_pin": del db.job["snapshot"]["model_bindings"]["asr"]
    elif change == "pin_revision": pin["fallbacks"][0]["revision"] = 2
    elif change == "pin_order": pin["fallbacks"].reverse()
    elif change == "extra_pin": pin["fallbacks"].append(reference(4))
    before = deepcopy(db.job["snapshot"])
    coordinator.auto_enroll_new_job("owner", "job", "request")
    assert not db.rows
    with pytest.raises(Conflict, match="supported_frozen_transcription"):
        coordinator.enroll_job("owner", "job", 3, "request")
    assert not db.rows and db.job["snapshot"] == before


@pytest.mark.parametrize("guard", ["running", "cancelled", "cancel_requested", "active_claim_id", "attempts", "revision"])
def test_existing_fresh_draft_guards_remain(guard):
    coordinator, db, _ = setup_coordinator()
    if guard in {"running", "cancelled"}: db.job["status"] = guard
    elif guard == "attempts": db.attempts = 1
    elif guard == "revision": db.job["revision"] += 1
    else: db.job[guard] = True
    with pytest.raises(Conflict, match="fresh_draft_revision"):
        coordinator.enroll_job("owner", "job", 3, "request")
    assert not db.rows


def test_auto_does_not_adopt_historical_runs():
    coordinator, db, _ = setup_coordinator()
    db.job["runs"] = [{"status": "failed"}]
    coordinator.auto_enroll_new_job("owner", "job", "request")
    assert not db.rows


def test_enrollment_replay_and_conflicts_are_unchanged():
    coordinator, db, _ = setup_coordinator()
    first = coordinator.enroll_job("owner", "job", 3, "request")
    assert coordinator.enroll_job("owner", "job", 3, "request") == first
    with pytest.raises(Conflict, match="request_changed"):
        coordinator.enroll_job("owner", "job", 4, "request")
    with pytest.raises(Conflict, match="already_enrolled"):
        coordinator.enroll_job("owner", "job", 4, "other")
    assert len(db.rows) == 1
