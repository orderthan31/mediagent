"""Authenticated shared subtitle documents, independent of execution/review."""
from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from video_service.subtitle_copies import SubtitleCopies
from video_service.object_store import ObjectStoreError


class SaveSubtitleCopy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    filename: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    srt: str = Field(min_length=1, max_length=16 * 1024 * 1024)


def mount_subtitle_copies(app, store, session_dependency):
    copies = SubtitleCopies(store)

    def storage_call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except ObjectStoreError as exc:
            status = exc.status if exc.status in {403, 404} else 503
            detail = {
                403: '자막 저장소 접근이 거부되었습니다.',
                404: '저장된 자막을 찾을 수 없습니다.',
            }.get(status, '자막 저장소 요청을 확인하지 못했습니다. 자동으로 다시 저장하지 않습니다.')
            if exc.code:
                detail = exc.code + ': ' + detail
            raise HTTPException(status, detail) from None
        except FileNotFoundError:
            raise HTTPException(404, '저장된 자막을 찾을 수 없습니다.') from None
        except OSError:
            raise HTTPException(503, '자막 저장소를 읽거나 쓰지 못했습니다.') from None

    @app.post('/api/subtitle-copies', status_code=201)
    def save_copy(body: SaveSubtitleCopy, actor=session_dependency):
        return storage_call(copies.save, actor['user']['id'], **body.model_dump())

    @app.get('/api/subtitle-copies')
    def saved_copies(
        after: str | None = Query(default=None, pattern=r'^[a-f0-9]{32}$'),
        actor=session_dependency,
    ):
        return storage_call(copies.list, after)

    @app.get('/api/subtitle-copies/{copy_id}')
    def saved_copy(copy_id: str, actor=session_dependency):
        return storage_call(copies.get, copy_id)
