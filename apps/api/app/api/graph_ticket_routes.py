"""Explicit new graph-ticket API, sharing owner/origin/plan contracts."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import Field
from video_service.graph_tickets import GraphTicketStore
from video_service.parallel_workflow import compile_graph
from video_service.workflow_definitions import DefinitionStore
from video_service.workflow_tickets import TicketConflict
from video_service.capacity import assert_capacity
from .workflow_ticket_routes import (TicketOptions, TicketCreate, PlanRequest, ConfirmRequest,
                                     body, respond, settings_module, preferences, asset_input, verify_input)

from .execution_approval_routes import GuardedRoute
router = APIRouter(prefix='/graph-tickets', route_class=GuardedRoute)


class GraphOptions(TicketOptions):
    branch_choices: dict[str, Literal['a', 'b', 'both']] = Field(default_factory=dict, max_length=100)


class GraphCreate(TicketCreate):
    options: GraphOptions = Field(default_factory=GraphOptions)


def store(request):
    return GraphTicketStore(settings_module().settings.storage_root, request.state.settings_owner)


@router.get('/runtime')
def runtime(request: Request):
    return {'connected': callable(getattr(request.app.state, 'graph_executor_factory', None)),
            'mode': getattr(request.app.state, 'graph_executor_label', '수동 분기·병렬 실행기'),
            'notice': '새 병렬 티켓만 사용합니다. 운영 미연결이면 실행하지 않으며 기존 큐/Worker를 시작하지 않습니다. 모델 성공과 다릅니다.'}


@router.post('/capability')
async def capability(request: Request):
    raw = await settings_module().serving_json(request, limit=131072)
    if not isinstance(raw, dict) or set(raw) != {'definition', 'choices'}:
        raise HTTPException(422, '편집 정의와 수동 선택을 함께 전달하세요.')
    return compile_graph(raw['definition'], raw['choices'])


@router.get('')
def list_tickets(request: Request):
    return respond(lambda: {'tickets': store(request).list()})


@router.post('', status_code=201)
async def create_ticket(request: Request):
    payload = await body(request, GraphCreate)
    identity = payload.model_dump(exclude={'request_id'})
    def create():
        def source():
            settings = settings_module().settings
            assert_capacity(settings.storage_root, settings.service_quota_bytes, settings.min_free_space_bytes, additional=262144)
            return asset_input(request, payload.asset_id)[0]
        return store(request).create(payload.request_id, identity,
            lambda: DefinitionStore(settings_module().settings.storage_root, request.state.settings_owner).get(payload.definition_id), source)
    return await run_in_threadpool(lambda: respond(create))


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
    return await run_in_threadpool(lambda: respond(confirm))


@router.post('/{identity}/start')
async def start_ticket(identity: str, request: Request):
    payload = await body(request, PlanRequest)
    def start():
        s = store(request)
        ticket = s.get(identity)
        if ticket['revision'] != payload.revision or not ticket['confirmation'] or ticket['confirmation']['token'] != payload.token:
            raise TicketConflict('티켓/계획/수동 선택을 새로 확인하세요.')
        factory = getattr(request.app.state, 'graph_executor_factory', None)
        if not callable(factory):
            raise TicketConflict('병렬 실행기 미연결입니다. 보류 상태와 기존 큐를 유지합니다.')
        source = verify_input(request, ticket)
        return s.run(identity, preferences(request), source, factory)
    return await run_in_threadpool(lambda: respond(start))


@router.get('/{identity}/artifacts/{node_id}/{port}')
def artifact(identity: str, node_id: str, port: str, request: Request, partial: bool = False):
    def download():
        path = store(request).artifact_path(identity, node_id, port, partial=partial)
        return FileResponse(path, filename=node_id + '-' + port + path.suffix)
    return respond(download)
