from contextlib import ExitStack
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.api import routes
from app.services.request_locks import admission_lock
from video_service.locking import job_lock
from video_service.models import JobStatus
from video_service.queue_control import QueueControl, QueueConflict, QUEUE_LOCK_ID

router = APIRouter(prefix='/api/queue', dependencies=[Depends(routes.authorize_job_request)])


class QueueUpdate(BaseModel):
    revision: int = Field(ge=0)
    paused: bool | None = None
    order: list[str] | None = Field(default=None, max_length=1000)


class QueueCancel(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=1000)


@router.get('')
def get_queue(request: Request):
    state = QueueControl(routes.repository.storage_root).read(request.state.owner_id)
    jobs = [job for job in routes.repository.list() if job.metadata.get('owner_id') == request.state.owner_id
            and job.status == JobStatus.QUEUED and not job.metadata.get('internal')]
    positions = {identity: index for index, identity in enumerate(state['order'])}
    jobs.sort(key=lambda job: (positions.get(job.job_id, len(positions)),
                              job.metadata.get('queued_at', job.created_at), job.job_id))
    return {**state, 'jobs': [job.job_id for job in jobs]}


@router.patch('')
def update_queue(payload: QueueUpdate, request: Request):
    repo = routes.repository
    with admission_lock(repo, QUEUE_LOCK_ID):
        if payload.order is not None:
            if len(set(payload.order)) != len(payload.order):
                raise HTTPException(422, '작업 순서에 중복이 있습니다.')
            for identity in payload.order:
                record = routes._read_job_or_404(identity)
                if record.metadata.get('owner_id') != request.state.owner_id or record.metadata.get('internal'):
                    raise HTTPException(404, '작업을 찾을 수 없습니다.')
                if record.status != JobStatus.QUEUED:
                    raise HTTPException(409, '이미 시작된 작업이 있습니다. 큐를 새로고침해 주세요.')
        try:
            return QueueControl(repo.storage_root).update(request.state.owner_id, payload.revision,
                                                         paused=payload.paused, order=payload.order)
        except QueueConflict as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post('/cancel-pending')
def cancel_pending(payload: QueueCancel, request: Request):
    repo = routes.repository
    identities = sorted(set(payload.job_ids))
    cancelled, skipped = [], []
    with admission_lock(repo, QUEUE_LOCK_ID), ExitStack() as locks:
        records = []
        # Authorize and acquire every state lock before changing any job.
        for identity in identities:
            locks.enter_context(job_lock(repo, identity))
            record = routes._read_job_or_404(identity)
            if record.metadata.get('owner_id') != request.state.owner_id or record.metadata.get('internal'):
                raise HTTPException(404, '작업을 찾을 수 없습니다.')
            records.append(record)
        for record in records:
            if record.status != JobStatus.QUEUED:
                skipped.append(record.job_id)
                continue
            repo.update_status(record.job_id, JobStatus.CANCELLED, message='대기 작업 취소',
                               metadata={'cancel_requested': True, 'stage_progress': None})
            cancelled.append(record.job_id)
    return {'cancelled': cancelled, 'skipped': skipped}
