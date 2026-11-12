"""Normal work-entry input checks only. No execution/session/preview endpoints."""
from fastapi import HTTPException
from video_service.object_store import ObjectStoreError
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from mideagent_orchestrator.face_inputs import FaceInputs


class FaceInputCheck(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    photo_asset_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    target_asset_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    engine_revision: int | None = Field(default=None, ge=1)
    engine_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    settings_revision: Literal[1] = 1
    preset: str = Field(min_length=1, max_length=32)
    video_codec: str = Field(min_length=1, max_length=32)


def mount_face_inputs(app, runtime, owner_dependency):
    inputs = FaceInputs(runtime)

    @app.get('/api/work-entry/faceswap-inputs')
    def choices(actor=owner_dependency):
        return inputs.choices()

    @app.post('/api/work-entry/faceswap-inputs/inspect')
    def inspect(body: FaceInputCheck, actor=owner_dependency):
        try:
            return inputs.public(inputs.inspect(actor, body.model_dump()))
        except ObjectStoreError as exc:
            status = exc.status if exc.status in {403, 404} else 503
            raise HTTPException(status, '원본 저장소를 확인하지 못했습니다. 입력을 다시 확인하세요.') from None
        except FileNotFoundError:
            raise HTTPException(404, '선택한 원본 파일을 찾을 수 없습니다.') from None
