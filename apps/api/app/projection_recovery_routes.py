"""Model-free artifact recovery routes, separate from execution/recovery-job admission."""

from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from video_service.postgres.projection_recovery import ProjectionRecovery


class ProjectionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str = Field(pattern="^[a-f0-9]{32}$")
    policy: Literal["packed_projection_v2", "packed_projection_v5"]


class ProjectionConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    acknowledge: StrictBool


def mount_projection_recoveries(app, runtime, owner_dependency):
    service = ProjectionRecovery(runtime)
    owner = owner_dependency
    base = "/api/renewal/jobs/{identity}/projection-recoveries"

    @app.get(base)
    def history(identity: str, actor=owner):
        return service.list(actor, identity)

    @app.post(base + "/preview")
    def preview(identity: str, body: ProjectionPreview, actor=owner):
        try:
            return service.preview(
                actor, identity, body.source_run_id, policy=body.policy
            )
        except PermissionError:
            raise HTTPException(403, "실행자만 재투영을 확인할 수 있습니다.") from None

    @app.post(base + "/{recovery_id}/confirm")
    def confirm(identity: str, recovery_id: str, body: ProjectionConfirm, actor=owner):
        try:
            return service.confirm(actor, identity, recovery_id, **body.model_dump())
        except PermissionError:
            raise HTTPException(403, "실행자만 재투영을 확인할 수 있습니다.") from None

    @app.get(base + "/{recovery_id}/files/{part}")
    def artifact(identity: str, recovery_id: str, part: str, actor=owner):
        return FileResponse(
            service.file(actor, identity, recovery_id, part),
            media_type="application/json",
            filename=recovery_id + "-" + part + ".json",
        )

    @app.get(base + "/sources/{run_id}/{part}")
    def material(identity: str, run_id: str, part: str, actor=owner):
        return FileResponse(
            service.material(actor, identity, run_id, part),
            media_type="audio/wav" if part == "audio" else "application/json",
            filename=run_id + "-" + part + (".wav" if part == "audio" else ".json"),
        )
