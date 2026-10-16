"""New AI decision tickets; never retrofit manual selections or legacy queue."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from video_service.work_tickets import WorkTicketStore, compile_work
from video_service.parallel_workflow import compile_graph
from video_service.workflow_definitions import DefinitionStore
from video_service.workflow_tickets import TicketConflict
from video_service.assets import AssetNotFoundError
from video_service.locking import JobBusyError
from video_service.capacity import assert_capacity
from .graph_ticket_routes import GraphCreate
from .workflow_ticket_routes import (PlanRequest, ConfirmRequest, body, settings_module, preferences, asset_input, verify_input)

router = APIRouter(prefix='/work-tickets')
UUID4 = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
SHA = r'^[0-9a-f]{64}$'


class RunRequest(PlanRequest):
    request_id: str = Field(pattern=UUID4)


class ReviewTarget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: str = Field(pattern=SHA)
    state_revision: int = Field(ge=1, strict=True)
    revision: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=SHA)


class ReviewSave(ReviewTarget):
    cues: list[dict] = Field(min_length=1, max_length=10000)


class ReviewDecision(ReviewTarget):
    request_id: str = Field(pattern=UUID4)
    action: Literal['approve', 'request_changes']
    reason: str = Field(default='', max_length=2000)


def respond(operation):
    try:
        return operation()
    except HTTPException:
        raise
    except TicketConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except JobBusyError:
        raise HTTPException(409, '다른 저장/실행이 진행 중입니다. 실행을 자동 재요청하지 않습니다.') from None
    except (FileNotFoundError, AssetNotFoundError):
        raise HTTPException(404, '이 계정의 영상/정의/검수 티켓/자료가 없습니다.') from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc) or '지원 자료/형식/계획을 확인하세요.') from None
    except Exception:
        raise HTTPException(503, '검수 저장소 접근 실패. 입력·과거 수정본은 보존됩니다.') from None


def store(request):
    return WorkTicketStore(settings_module().settings.storage_root, request.state.settings_owner)


def verified_document(request, identity, node):
    s = store(request)
    record = s.get(identity)
    source = verify_input(request, record)
    from video_service.graph_tickets import file_sha
    if file_sha(source) != record.get('source_sha256'):
        raise TicketConflict('검수 원본 SHA가 변경되었습니다.')
    s.review_input_path(identity, node, source)
    return s.review_document(identity, node)


def capacity(additional):
    settings = settings_module().settings
    assert_capacity(settings.storage_root, settings.service_quota_bytes, settings.min_free_space_bytes, additional=additional)


@router.get('/runtime')
def runtime(request: Request):
    return {'connected': callable(getattr(request.app.state, 'work_executor_factory', None)),
            'mode': getattr(request.app.state, 'work_executor_label', '등록 모델 워크플로우 실행기'),
            'notice': '저장 워크플로우와 고정 노드 모델을 사용합니다. 계획 확인과 실행은 별도이며 운영 미연결·기존 티켓/큐 보존을 유지합니다. 운영 미연결·기존 큐 미소비를 유지합니다.'}


@router.post('/capability')
async def capability(request: Request):
    raw = await settings_module().serving_json(request, limit=131072)
    if not isinstance(raw, dict) or set(raw) != {'definition', 'choices'}:
        raise HTTPException(422, '편집 정의와 수동 선택을 함께 전달하세요.')
    return compile_work(raw['definition'], {'branch_choices':raw['choices']})


@router.get('')
def list_tickets(request: Request):
    return respond(lambda: {'tickets': store(request).list()})


@router.post('', status_code=201)
async def create_ticket(request: Request):
    payload = await body(request, GraphCreate)
    def create():
        capacity(262144)
        return store(request).create(payload.request_id, payload.model_dump(exclude={'request_id'}),
            lambda: DefinitionStore(settings_module().settings.storage_root, request.state.settings_owner).get(payload.definition_id),
            lambda: asset_input(request, payload.asset_id)[0])
    return respond(create)


@router.get('/{identity}')
def get_ticket(identity: str, request: Request):
    return respond(lambda: store(request).get(identity))


@router.get('/{identity}/plan')
def get_plan(identity: str, request: Request):
    def plan():
        s = store(request)
        verify_input(request, s.get(identity))
        return s.plan(identity, preferences(request))
    return respond(plan)


@router.post('/{identity}/confirm')
async def confirm_ticket(identity: str, request: Request):
    payload = await body(request, ConfirmRequest)
    def confirm():
        s = store(request)
        verify_input(request, s.get(identity))
        return s.confirm(identity, payload.revision, payload.token, payload.paid_confirmed, preferences(request))
    return respond(confirm)


async def run_request(identity, request, operation):
    payload = await body(request, RunRequest)
    def run():
        s = store(request)
        args = (identity, payload.request_id, payload.revision, payload.token, operation)
        existing = s.replay(*args)
        if existing is not None:
            return existing
        factory = getattr(request.app.state, 'work_executor_factory', None)
        if not callable(factory):
            raise TicketConflict('작업 실행기 미연결입니다. 보류/대기를 보존하며 기존 큐/render를 사용하지 않습니다.')
        source = verify_input(request, s.get(identity))
        return s.run(identity, preferences(request), source, factory, request_id=payload.request_id,
                     revision=payload.revision, token=payload.token, operation=operation)
    return await run_in_threadpool(lambda: respond(run))


@router.post('/{identity}/start')
async def start(identity: str, request: Request):
    return await run_request(identity, request, 'start')


@router.post('/{identity}/continue')
async def continue_ticket(identity: str, request: Request):
    return await run_request(identity, request, 'continue')


@router.get('/{identity}/reviews/{node}')
def get_review(identity: str, node: str, request: Request):
    return respond(lambda: store(request).review_document(identity, node).get())


@router.get('/{identity}/reviews/{node}/input')
def review_input(identity: str, node: str, request: Request):
    def download():
        s = store(request)
        source = verify_input(request, s.get(identity))
        return FileResponse(s.review_input_path(identity, node, source))
    return respond(download)


@router.get('/{identity}/reviews/{node}/revisions/{revision}')
def review_version(identity: str, node: str, revision: int, request: Request):
    def version():
        doc = store(request).review_document(identity, node)
        if str(revision) not in doc._read()['versions']:
            raise FileNotFoundError('해당 수정본이 없습니다.')
        return doc.version(revision)
    return respond(version)


@router.put('/{identity}/reviews/{node}')
async def save_review(identity: str, node: str, request: Request):
    raw = await settings_module().serving_json(request, limit=2*1024*1024)
    try:
        payload = ReviewSave.model_validate(raw)
    except ValidationError:
        raise HTTPException(422, '검수 대상/revision/SHA와 구간 배열만 저장할 수 있습니다.') from None
    def save():
        return verified_document(request, identity, node).save(payload.state_revision, payload.revision, payload.sha256,
                                                                  payload.target, payload.cues, capacity_check=capacity)
    return await run_in_threadpool(lambda: respond(save))


@router.post('/{identity}/reviews/{node}/decision')
async def decision(identity: str, node: str, request: Request):
    payload = await body(request, ReviewDecision)
    def decide():
        doc = verified_document(request, identity, node)
        args = (payload.state_revision, payload.revision, payload.sha256, payload.target, payload.request_id)
        return doc.approve(*args) if payload.action == 'approve' else doc.request_changes(*args, payload.reason)
    return await run_in_threadpool(lambda: respond(decide))


@router.get('/{identity}/artifacts/{node_id}/{port}')
def artifact(identity: str, node_id: str, port: str, request: Request, partial: bool = False):
    return respond(lambda: FileResponse(store(request).artifact_path(identity, node_id, port, partial=partial), filename=node_id + '-' + port))
