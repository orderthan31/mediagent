"""Authenticated owner-controlled unit recovery; never automatically dispatch."""
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, StrictBool, StrictInt
from video_service.postgres import Conflict, Missing
from video_service.postgres.unit_recovery import RoleUnitRecovery, RecoveryUnavailable

from .renewal import Body


class UnitDecision(Body):
    unit_index: StrictInt = Field(ge=0)
    action: Literal['retry', 'skip', 'manual']
    candidate_index: StrictInt | None = Field(default=None, ge=0)
    value: list[dict] | None = Field(default=None, max_length=10000)


class UnitPreview(Body):
    job_revision: StrictInt = Field(ge=0)
    recovery_revision: StrictInt = Field(ge=0)
    context_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    decisions: list[UnitDecision] = Field(max_length=10000)


class UnitApproval(UnitPreview):
    request_id: str = Field(min_length=1, max_length=100)
    preview_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    approve_calls: StrictBool


class UnitExecute(Body):
    request_id: str = Field(min_length=1, max_length=100)


def mount_unit_recovery_routes(app, runtime, owner_dependency, *, executor=None, continue_job=None, execution_enabled=True):
    service = RoleUnitRecovery(runtime, executor=executor)
    base = '/api/renewal/jobs/{job}/runs/{run}/unit-recovery'

    def invoke(method, *args):
        try:
            return method(*args)
        except RecoveryUnavailable:
            raise HTTPException(503, 'unit_recovery_migration_required') from None
        except PermissionError:
            raise HTTPException(403, 'unit_recovery_owner_required') from None
        except Missing:
            raise HTTPException(404, 'unit_recovery_missing') from None
        except Conflict as error:
            # Only our static machine codes, never raw SQL/provider/credential errors.
            code = str(error)
            if not code.startswith(('unit_recovery_', 'invalid_unit_recovery_', 'unsupported_role')) or not all(c.isalnum() or c == '_' for c in code):
                code = 'unit_recovery_conflict'
            raise HTTPException(409, code) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(409, 'unit_recovery_invalid_evidence') from None

    @app.get(base)
    def inspect(job: str, run: str, owner=owner_dependency):
        return invoke(service.inspect, owner, job, run)

    @app.post(base + '/preview')
    def preview(job: str, run: str, body: UnitPreview, owner=owner_dependency):
        return invoke(service.preview, owner, job, run, body.model_dump(exclude_unset=True))

    @app.post(base + '/decisions')
    def decide(job: str, run: str, body: UnitApproval, owner=owner_dependency):
        return invoke(service.decide, owner, job, run, body.model_dump(exclude_unset=True))

    @app.post(base + '/execute')
    def execute(job: str, run: str, body: UnitExecute, owner=owner_dependency):
        if not execution_enabled:
            raise HTTPException(403, 'unit_recovery_execution_disabled')
        return invoke(service.execute, owner, job, run, body.request_id)

    @app.post(base + '/continue')
    def proceed(job: str, run: str, body: UnitExecute, owner=owner_dependency):
        if not execution_enabled:
            raise HTTPException(403, 'unit_recovery_execution_disabled')
        # Authorization happens even when canonical adoption is not configured.
        state = invoke(service.inspect, owner, job, run)
        if not state['access']['can_manage']:
            raise HTTPException(403, 'unit_recovery_owner_required')
        accept = getattr(runtime, 'accept_role_recovery', None)
        if accept is None:
            raise HTTPException(503, 'unit_recovery_adoption_unavailable')
        result = invoke(accept, owner, job, run, body.request_id)
        if continue_job is not None:
            continue_job(owner, job)
        return result

    return service
