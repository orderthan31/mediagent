from io import BytesIO
import hashlib
import shutil
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, UUID4

from app.api import routes
from app.api.asset_routes import asset_errors
from app.core.config import settings
from video_service.assets import VideoAssetRepository
from video_service.capacity import assert_capacity, remaining_reservations
from video_service.faceswap import FaceSwapSessions, MAX_SOURCE_BYTES, digest, reservation, public_capabilities
from video_service.locking import job_lock, download_lock
from video_service.models import JobRecord, JobOptions, JobStatus, utc_now_iso, TERMINAL_STATUSES
from video_service.storage import read_json, write_json_atomic

router = APIRouter(prefix='/api', dependencies=[Depends(routes.authorize_job_request)])


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SessionCreate(Strict):
    request_id: UUID4


class Options(Strict):
    reference_frame: int = Field(default=1, ge=1, le=10000000)
    face_position: int = Field(default=-1, ge=-1, le=100)
    source_position: int = Field(default=-1, ge=-1, le=100)
    distance: float = Field(default=.3, ge=.05, le=1, multiple_of=.05, allow_inf_nan=False)
    preset: Literal['fast', 'balanced', 'quality'] = 'balanced'
    video_codec: Literal['h264', 'hevc'] = 'h264'


class SessionUpdate(Strict):
    revision: int = Field(ge=0)
    settings: Options


class Execute(Strict):
    request_id: UUID4
    revision: int = Field(ge=0)
    operation: Literal['analyze_source', 'analyze_reference', 'preview', 'render']
    preview_frame: int = Field(default=1, ge=1, le=10000000)
    preview_job_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')


def owned(session_id, request):
    store = FaceSwapSessions(routes.repository)
    return store, store.read_session(session_id, request.state.owner_id)


def capacity(additional):
    repo = routes.repository
    assert_capacity(repo.storage_root, settings.service_quota_bytes, settings.min_free_space_bytes,
                    remaining_reservations(repo) + additional)


@router.get('/faceswap/capabilities')
def capabilities():
    return public_capabilities(routes.repository.storage_root)


@router.get('/videos/{asset_id}/faceswap-sessions')
def list_sessions(asset_id: str, request: Request):
    with asset_errors():
        VideoAssetRepository(routes.repository).read(asset_id, owner_id=request.state.owner_id)
        return {'sessions': FaceSwapSessions(routes.repository).sessions(request.state.owner_id, asset_id)}


@router.post('/videos/{asset_id}/faceswap-sessions', status_code=201)
def create_session(asset_id: str, payload: SessionCreate, request: Request):
    repo = routes.repository
    with asset_errors(), job_lock(repo, '0' * 32):
        VideoAssetRepository(repo).read(asset_id, owner_id=request.state.owner_id)
        capacity(4096)
        try:
            return FaceSwapSessions(repo).create(asset_id, request.state.owner_id, str(payload.request_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.get('/faceswap/sessions/{session_id}')
def get_session(session_id: str, request: Request):
    return owned(session_id, request)[1]


@router.put('/faceswap/sessions/{session_id}')
def update_session(session_id: str, payload: SessionUpdate, request: Request):
    store, _ = owned(session_id, request)
    with job_lock(store, session_id):
        record = store.read_session(session_id, request.state.owner_id)
        if record['revision'] != payload.revision:
            raise HTTPException(409, '설정이 변경되었습니다. 다시 불러오세요.')
        record.update(settings=payload.settings.model_dump(), revision=record['revision'] + 1)
        store.save_session(record)
        return record


@router.delete('/faceswap/sessions/{session_id}', status_code=204)
def delete_session(session_id: str, request: Request):
    store, _ = owned(session_id, request)
    with job_lock(routes.repository, '0' * 32), job_lock(store, session_id, 'execution'), job_lock(store, session_id):
        store.read_session(session_id, request.state.owner_id)
        active = [j for j in routes.repository.list() if j.metadata.get('faceswap', {}).get('session_id') == session_id
                  and j.status not in TERMINAL_STATUSES]
        if active:
            raise HTTPException(409, '진행 중인 얼굴 합성 요청을 먼저 취소하세요.')
        store.delete_job_dir(session_id)


@router.post('/faceswap/sessions/{session_id}/source')
async def upload_source(session_id: str, request: Request, revision: int = Query(ge=0)):
    store, _ = owned(session_id, request)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_SOURCE_BYTES:
            raise HTTPException(413, 'Source 이미지는 최대 10MB입니다.')
        body.extend(chunk)
    try:
        with Image.open(BytesIO(body)) as image:
            if image.format not in {'JPEG', 'PNG'} or image.width * image.height > 24000000:
                raise ValueError('JPEG/PNG, 최대 2400만 화소 이미지를 사용하세요.')
            normalized = ImageOps.exif_transpose(image).convert('RGB')
            encoded = BytesIO()
            normalized.save(encoded, format='JPEG', quality=95)
            content = encoded.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, '올바른 JPEG/PNG 이미지를 사용하세요.') from exc
    with asset_errors(), job_lock(routes.repository, '0' * 32), job_lock(store, session_id):
        record = store.read_session(session_id, request.state.owner_id)
        if record['revision'] != revision:
            raise HTTPException(409, '설정이 변경되었습니다. 다시 불러오세요.')
        capacity(len(content) + 4096)
        filename = uuid4().hex + '.jpg'
        (store.job_dir(session_id) / filename).write_bytes(content)
        record.update(source_file=filename, source_sha256=hashlib.sha256(content).hexdigest(),
                      revision=revision + 1)
        record['settings']['source_position'] = -1
        store.save_session(record)
        return record


@router.get('/faceswap/sessions/{session_id}/requests')
def list_requests(session_id: str, request: Request):
    owned(session_id, request)
    return {'jobs': [routes.job_to_response(j) for j in routes.repository.list()
                     if j.metadata.get('faceswap', {}).get('session_id') == session_id
                     and j.metadata.get('owner_id') == request.state.owner_id]}


@router.post('/faceswap/sessions/{session_id}/requests', status_code=202)
def execute(session_id: str, payload: Execute, request: Request):
    repo = routes.repository
    store, _ = owned(session_id, request)
    with asset_errors(), job_lock(repo, '0' * 32), job_lock(store, session_id):
        record = store.read_session(session_id, request.state.owner_id)
        identity = {'session_id': session_id, **payload.model_dump(mode='json')}
        for job in repo.list():
            if job.metadata.get('owner_id') == request.state.owner_id and job.metadata.get('faceswap_request_id') == str(payload.request_id):
                if job.metadata['faceswap_request'] != identity:
                    raise HTTPException(409, '요청 ID가 다른 설정에 사용되었습니다.')
                return routes.job_to_response(job)
        if record['revision'] != payload.revision:
            raise HTTPException(409, '설정이 변경되었습니다. 다시 불러오세요.')
        cap = public_capabilities(repo.storage_root)
        if not cap.get('ready'):
            raise HTTPException(503, cap.get('reason', '얼굴 합성 Worker 준비 중'))
        if payload.operation != 'analyze_reference' and not record['source_file']:
            raise HTTPException(422, 'Source 이미지를 먼저 등록하세요.')
        if payload.operation in {'preview', 'render'} and min(record['settings']['source_position'], record['settings']['face_position']) < 0:
            raise HTTPException(422, 'Source와 교체 대상 얼굴을 직접 선택하세요.')
        pending = [j for j in repo.list() if j.metadata.get('faceswap', {}).get('session_id') == session_id
                   and j.status not in TERMINAL_STATUSES]
        if len(pending) >= 3:
            raise HTTPException(409, '대기 요청은 최대 3개입니다. 완료를 기다리거나 취소하세요.')
        snapshot = {key: record[key] for key in ('session_id', 'asset_id', 'revision', 'settings', 'source_sha256')}
        snapshot['fingerprint'] = cap['fingerprint']
        key = digest(snapshot)
        if payload.operation == 'render':
            if not payload.preview_job_id:
                raise HTTPException(422, '현재 설정의 미리보기를 먼저 확인하세요.')
            preview = repo.read(payload.preview_job_id)
            if (preview.metadata.get('owner_id') != request.state.owner_id or
                    preview.metadata.get('faceswap_operation') != 'preview' or
                    preview.metadata.get('faceswap_key') != key or preview.status != JobStatus.COMPLETED or
                    preview.metadata.get('results_expired_at')):
                raise HTTPException(409, '현재 설정으로 미리보기를 다시 생성하세요.')
        assets = VideoAssetRepository(repo)
        asset = assets.read(record['asset_id'], owner_id=request.state.owner_id)
        reserved = reservation(asset, payload.operation == 'render')
        capacity(reserved)
        job_id = uuid4().hex
        directory = repo.job_dir(job_id)
        for name in ('input', 'work', 'output'):
            (directory / name).mkdir(parents=True, exist_ok=True)
        if record['source_file']:
            shutil.copyfile(store.job_dir(session_id) / record['source_file'], directory / 'input/source.jpg')
        write_json_atomic(directory / 'input/faceswap.json', snapshot)
        job = JobRecord(job_id, JobStatus.QUEUED, asset['original_filename'], asset['source_filename'],
                        asset['size_bytes'], uploaded_bytes=asset['size_bytes'],
                        options=JobOptions(subtitle_mode='none', video_codec=record['settings']['video_codec']),
                        metadata={'owner_id': request.state.owner_id, 'asset_id': asset['asset_id'],
                                  'source_asset_id': asset['asset_id'], 'faceswap': snapshot,
                                  'faceswap_key': key, 'faceswap_operation': payload.operation,
                                  'faceswap_request_id': str(payload.request_id), 'faceswap_request': identity,
                                  'preview_frame': payload.preview_frame, 'reserved_bytes': reserved,
                                  'queued_at': utc_now_iso(), 'internal': payload.operation != 'render',
                                  'workflow': {'version': 2, 'template': 'faceswap',
                                               'stages': ['analyze', 'faceswap', 'validate_video']}})
        repo.save(job)
        return routes.job_to_response(job)


@router.get('/faceswap/jobs/{job_id}/files/{filename}')
def image_result(job_id: str, filename: str):
    repo = routes.repository
    with download_lock(repo, job_id):
        job = repo.read(job_id)
        if job.status != JobStatus.COMPLETED or filename not in job.metadata.get('faceswap_files', []):
            raise HTTPException(404, '결과 이미지를 찾을 수 없습니다.')
        if job.metadata.get('results_expired_at'):
            raise HTTPException(410, '결과가 만료되었습니다.')
        path = repo.job_dir(job_id) / 'output' / filename
        if not path.is_file():
            raise HTTPException(404, '결과 이미지를 찾을 수 없습니다.')
        return Response(path.read_bytes(), media_type='image/png')
