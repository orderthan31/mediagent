import importlib.util
from types import SimpleNamespace
from test_execution import db as _db, admin as _admin, movie as _movie
from test_model_role_orchestration import formal
from video_service.model_role_coordinator import ModelRoleCoordinator

db, admin, movie = _db, _admin, _movie


def test_new_job_connects_saved_roles_without_a_user_enable_step(
    db, admin, movie, tmp_path
):
    runtime, owner, job = formal(db, admin, movie, tmp_path, prepare=False)
    coordinator = ModelRoleCoordinator(
        runtime,
        SimpleNamespace(
            model_role_factory=lambda: None, model_role_result_store=runtime.store
        ),
    )
    after = coordinator.auto_enroll_new_job(owner, job["id"], "auto-role-request")
    assert after["status"] == "draft" and after["runs"] == []
    assert coordinator.enrolled(runtime, owner, job["id"])
    assert (
        coordinator.auto_enroll_new_job(owner, job["id"], "same-job-another-request")[
            "revision"
        ]
        == after["revision"]
    )
