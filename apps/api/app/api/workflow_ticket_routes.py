"""Explicit held sequential tickets, separate from existing runnable job admission."""
from types import SimpleNamespace
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from video_service.workflow_definitions import DefinitionStore
from video_service.workflow_tickets import TicketStore, TicketConflict
from video_service.llm_settings import LLMSettingsStore
from video_service.sequential_workflow import compile_sequence
from video_service.assets import VideoAssetRepository, AssetNotFoundError
from video_service.capacity import assert_capacity
from video_service.locking import JobBusyError

router=APIRouter(prefix='/workflow-tickets')
ID=r'^[0-9a-f]{32}$'


def settings_module():
    # Parent router owns configuration/auth and mounts this child after definition.
    from app.api import settings_routes
    return settings_routes


class TicketOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_language:str=Field(default='auto',pattern=r'^(auto|[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)$')
    target_language:str=Field(default='ko',pattern=r'^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$')
    video_description:str=Field(default='',max_length=2000)


class TicketCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
    definition_id:str=Field(pattern=ID)
    definition_revision:int=Field(ge=1,strict=True)
    asset_id:str=Field(pattern=ID)
    options:TicketOptions=Field(default_factory=TicketOptions)


class PlanRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1,strict=True)
    token:str=Field(pattern=r'^[0-9a-f]{64}$')


class ConfirmRequest(PlanRequest):
    paid_confirmed:StrictBool


def respond(operation):
    try:return operation()
    except TicketConflict as exc:raise HTTPException(409,str(exc)) from None
    except JobBusyError:raise HTTPException(409,'다른 티켓 저장/실행이 진행 중입니다. 자동 실행 재시도는 하지 않습니다.') from None
    except (FileNotFoundError,AssetNotFoundError):raise HTTPException(404,'이 계정의 영상/정의/티켓/산출물이 없습니다.') from None
    except (ValueError,TypeError):raise HTTPException(422,'선택한 입력·정의 revision·순차 범위·계획/비용 확인을 검토하세요.') from None
    except Exception:raise HTTPException(503,'티켓 저장소 접근에 실패했습니다. 기존 티켓과 입력은 유지됩니다.') from None


def store(request):return TicketStore(settings_module().settings.storage_root,request.state.settings_owner)
def preferences(request):return LLMSettingsStore(settings_module().settings.storage_root).resolve(request.state.settings_owner)


def asset_input(request,asset_id):
    assets=VideoAssetRepository(SimpleNamespace(storage_root=settings_module().settings.storage_root))
    asset=assets.read(asset_id,owner_id=request.state.settings_owner);source=assets.source_path(asset);stat=source.stat()
    if stat.st_size!=asset['size_bytes']:raise TicketConflict('원본 영상 상태가 등록 정보와 다릅니다.')
    return {'asset_id':asset['asset_id'],'original_filename':asset['original_filename'],'size_bytes':stat.st_size,'source_mtime_ns':stat.st_mtime_ns},source


def verify_input(request,ticket):
    current,source=asset_input(request,ticket['asset']['asset_id'])
    if current!=ticket['asset']:raise TicketConflict('티켓 생성 때 선택한 영상 정보가 변경되었습니다.')
    return source


async def body(request,model):
    raw=await settings_module().serving_json(request,limit=131072)
    try:return model.model_validate(raw)
    except ValidationError:raise HTTPException(422,'요청 ID·정의/영상ID·revision·언어옵션·명시 확인 형식을 확인하세요. 추가 키/실행 옵션은 허용하지 않습니다.') from None


@router.get('/runtime')
def runtime(request:Request):
    connected=callable(getattr(request.app.state,'workflow_executor_factory',None))
    return {'connected':connected,'mode':getattr(request.app.state,'workflow_executor_label','수동 순차 실행기'),
            'notice':'생성/확인은 기존 큐에 넣지 않습니다. 실행기 미연결이면 실행하지 않습니다. 모델 연결/추론 성공과 다릅니다.'}


@router.post('/capability')
async def capability(request:Request):return compile_sequence(await settings_module().serving_json(request,limit=131072))


@router.get('')
def list_tickets(request:Request):return respond(lambda:{'tickets':store(request).list()})


@router.post('',status_code=201)
async def create_ticket(request:Request):
    payload=await body(request,TicketCreate);identity=payload.model_dump(exclude={'request_id'})
    def create():
        def source():
            assert_capacity(settings_module().settings.storage_root,settings_module().settings.service_quota_bytes,settings_module().settings.min_free_space_bytes,additional=262144)
            return asset_input(request,payload.asset_id)[0]
        return store(request).create(payload.request_id,identity,lambda:DefinitionStore(settings_module().settings.storage_root,request.state.settings_owner).get(payload.definition_id),source)
    return respond(create)


@router.get('/{identity}')
def get_ticket(identity:str,request:Request):return respond(lambda:store(request).get(identity))


@router.get('/{identity}/plan')
def get_plan(identity:str,request:Request):
    def plan():
        s=store(request);verify_input(request,s.get(identity));return s.plan(identity,preferences(request))
    return respond(plan)


@router.post('/{identity}/confirm')
async def confirm_ticket(identity:str,request:Request):
    payload=await body(request,ConfirmRequest)
    def confirm():
        s=store(request);verify_input(request,s.get(identity));return s.confirm(identity,payload.revision,payload.token,payload.paid_confirmed,preferences(request))
    return respond(confirm)


@router.post('/{identity}/start')
async def start_ticket(identity:str,request:Request):
    payload=await body(request,PlanRequest)
    def start():
        s=store(request);ticket=s.get(identity)
        if ticket['revision']!=payload.revision or not ticket['confirmation'] or ticket['confirmation']['token']!=payload.token:raise TicketConflict('티켓/확인 계획이 다릅니다. 새 계획을 확인하세요.')
        factory=getattr(request.app.state,'workflow_executor_factory',None)
        if not callable(factory):raise TicketConflict('새 순차 실행기가 연결되지 않았습니다. 보류/확인 상태로 저장하며 기존 큐는 소비하지 않습니다.')
        source=verify_input(request,ticket)
        return s.run(identity,preferences(request),source,factory)
    return await run_in_threadpool(lambda:respond(start))


@router.get('/{identity}/artifacts/{node_id}/{port}')
def artifact(identity:str,node_id:str,port:str,request:Request,partial:bool=False):
    def download():
        path=store(request).artifact_path(identity,node_id,port,partial=partial)
        return FileResponse(path,filename=node_id+'-'+port+path.suffix)
    return respond(download)
