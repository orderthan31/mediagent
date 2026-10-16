"""Workflow-centered read-only inspection; preserves existing ticket APIs."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from video_service.workflow_entry import inspect_workflow
from video_service.workflow_definitions import DefinitionStore
from video_service.workflow_tickets import TicketConflict
from .workflow_ticket_routes import body, settings_module
from .review_ticket_routes import respond

router=APIRouter(prefix='/work-entry')


class InspectRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definition_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    definition_revision:int=Field(strict=True,ge=1)


@router.post('/inspect')
async def inspect(request:Request):
    payload=await body(request,InspectRequest)
    def read():
        definition=DefinitionStore(settings_module().settings.storage_root,request.state.settings_owner).get(payload.definition_id)
        if definition['revision']!=payload.definition_revision:
            raise TicketConflict('저장 워크플로우가 변경되었습니다. 흐름/설정을 새로 확인하세요.')
        result=inspect_workflow(definition)
        factories={'sequential':'workflow_executor_factory','graph':'graph_executor_factory','review':'review_executor_factory','decision':'decision_executor_factory'}
        models=ModelRegistry(settings_module().settings.storage_root,request.state.settings_owner)
        from video_service.model_registry import MODEL_ROLES
        result['model_ready']=True
        for summary,node in zip(result['summary'],definition['nodes']):
            if node['type'] in MODEL_ROLES:
                try:
                    if 'model_ref' not in node:
                        raise ValueError('노드에 호환 등록 모델을 연결하세요.')
                    summary['model_ref']=node['model_ref']
                    summary['model']=models.resolve(node['model_ref'],node['type'])
                    summary['model_availability']=models.availability(node['model_ref'],node['type'])
                except (ValueError,FileNotFoundError) as exc:
                    result['model_ready']=False
                    summary['model_error']=str(exc) or '해당 owner의 등록 모델/revision이 없습니다.'
        result['runtime_connected']=callable(getattr(request.app.state,factories.get(result['contract'],'_absent_factory'),None))
        return result
    return await run_in_threadpool(lambda:respond(read))


from .graph_ticket_routes import GraphOptions
from .workflow_ticket_routes import preferences,asset_input
from .review_ticket_routes import capacity,UUID4,SHA
from video_service.model_registry import ModelRegistry,ModelUnavailable,ModelConflict
from video_service.work_tickets import WorkTicketStore
from video_service.workflow_entry import preview_work
from video_service.locking import _file_lock
from starlette.concurrency import run_in_threadpool
from fastapi import HTTPException


class PreviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definition_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    definition_revision:int=Field(strict=True,ge=1)
    asset_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    options:GraphOptions=Field(default_factory=GraphOptions)
    recovery_enabled:bool=Field(default=False,strict=True)


class EntryCreate(PreviewRequest):
    request_id:str=Field(pattern=UUID4)
    token:str=Field(pattern=SHA)
    paid_confirmed:bool=Field(strict=True)


def registry(request):
    return ModelRegistry(settings_module().settings.storage_root,request.state.settings_owner)


def preview_inputs(request,payload):
    definition=DefinitionStore(settings_module().settings.storage_root,request.state.settings_owner).get(payload.definition_id)
    if definition['revision']!=payload.definition_revision:
        raise TicketConflict('저장 워크플로우가 변경되었습니다. 새 흐름·계획을 확인하세요.')
    asset=asset_input(request,payload.asset_id)[0]
    pref=preferences(request)
    options=payload.options.model_dump()
    quote=preview_work(definition,asset,pref,registry(request),options)
    if payload.recovery_enabled:
        from video_service.workflow_tickets import digest
        quote['token']=digest({'base':quote['token'],'recovery_contract':'recovery-v1'})
    quote['recovery_enabled']=payload.recovery_enabled
    return definition,asset,pref,options,quote


def entry_respond(operation):
    def checked():
        try:
            return operation()
        except (ModelUnavailable,ModelConflict) as exc:
            raise HTTPException(409,str(exc)) from None
    return respond(checked)


@router.post('/preview')
async def preview(request:Request):
    payload=await body(request,PreviewRequest)
    return await run_in_threadpool(lambda:entry_respond(lambda:preview_inputs(request,payload)[-1]))


@router.post('/create',status_code=201)
async def create(request:Request):
    payload=await body(request,EntryCreate)
    def prepare():
        root=settings_module().settings.storage_root
        owner=request.state.settings_owner
        models=registry(request)
        models.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        with _file_lock(models.directory/'registry.lock'):
            from video_service.recovery_tickets import RecoveryTicketStore
            tickets=(RecoveryTicketStore if payload.recovery_enabled else WorkTicketStore)(root,owner)
            identity=payload.model_dump(exclude={'request_id','token','paid_confirmed','recovery_enabled'})
            for existing in tickets.list():
                if existing['request_id']==payload.request_id:
                    if existing['request']!=identity or existing.get('entry_confirmation')!={'token':payload.token,'paid_confirmed':payload.paid_confirmed}:
                        raise TicketConflict('같은 생성 요청에 다른 입력/확인을 사용할 수 없습니다.')
                    return existing
            definition,asset,pref,options,quote=preview_inputs(request,payload)
            if payload.token!=quote['token']:
                raise TicketConflict('영상/흐름/모델 사용 상태/서빙이 바뀌었습니다. 새 계획을 확인하세요.')
            if quote['paid_roles'] and not payload.paid_confirmed:
                raise ValueError('계획에 있는 모델 호출/비용 역할의 명시 확인이 필요합니다.')
            capacity(524288)
            created=tickets.create(payload.request_id,identity,lambda:DefinitionStore(root,owner).get(payload.definition_id),lambda:asset_input(request,payload.asset_id)[0])
            actual=tickets.plan(created['id'],pref)
            if actual['model_bindings']!=quote['model_bindings'] or actual['eligible_steps']!=quote['eligible_steps'] or actual['paid_roles']!=quote['paid_roles']:
                raise TicketConflict('확인한 모델/미실행 계획이 달라 준비 티켓만 보존합니다. 실행하지 않았습니다.')
            confirmed=tickets.confirm(created['id'],created['revision'],actual['token'],payload.paid_confirmed,pref)
            confirmed['entry_confirmation']={'token':payload.token,'paid_confirmed':payload.paid_confirmed}
            tickets._save(confirmed)
            return tickets.get(confirmed['id'])
    return await run_in_threadpool(lambda:entry_respond(prepare))
