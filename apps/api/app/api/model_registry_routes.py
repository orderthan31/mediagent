"""Registered models only: no credential mutation and no provider calls."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel,ConfigDict,Field
from starlette.concurrency import run_in_threadpool
from video_service.model_registry import ModelRegistry, ModelConflict, ModelUnavailable, compatible_uses
from video_service.llm_providers import PROVIDERS,STT_MODELS
from .workflow_ticket_routes import settings_module,body
from .review_ticket_routes import respond,capacity

router=APIRouter(prefix='/registered-models')


class ModelBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(strict=True,ge=0)
    name:str=Field(min_length=1,max_length=80)
    provider:str=Field(min_length=1,max_length=40)
    model:str=Field(min_length=1,max_length=200)
    uses:list[str]=Field(min_length=1,max_length=3)


class AvailabilityBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(strict=True,ge=1)
    active:bool=Field(strict=True)


def store(request):
    return ModelRegistry(settings_module().settings.storage_root,request.state.settings_owner)


def checked(operation):
    try:
        return respond(operation)
    except HTTPException as exc:
        # Store CAS errors have a stable conflict code rather than a generic schema error.
        if isinstance(exc.__context__,ModelConflict):
            raise HTTPException(409,str(exc.__context__)) from None
        raise


@router.get('')
def list_models(request:Request):
    return checked(lambda:{'models':store(request).list(),'providers':{key:config['label'] for key,config in PROVIDERS.items()},
                           'stt_models':STT_MODELS,'connection':'unverified','notice':'등록·키 보유·adapter 형식 호환은 실연결/추론 성공이 아닙니다. 키는 기존 보관소에서만 관리합니다.'})


@router.post('/compatibility')
async def compatibility(request:Request):
    raw=await settings_module().serving_json(request,limit=4096)
    if not isinstance(raw,dict) or set(raw)!={'provider','model'} or any(not isinstance(raw[k],str) for k in raw):
        raise HTTPException(422,'provider/model만 검사할 수 있습니다.')
    uses=compatible_uses(raw['provider'],raw['model'])
    return {'uses':uses,'connection':'unverified','reason':'' if uses else '지원하는 노드 adapter/provider/model 형식 조합이 아닙니다. 임의 용도 선언으로 우회할 수 없습니다.'}


@router.get('/{identity}')
def get_model(identity:str,request:Request):
    return checked(lambda:store(request).get(identity))


@router.put('/{identity}')
async def save_model(identity:str,request:Request):
    payload=await body(request,ModelBody)
    def save():
        capacity(65536)
        try:
            return store(request).save(identity,payload.model_dump())
        except ModelConflict as exc:
            raise HTTPException(409,str(exc)) from None
    return await run_in_threadpool(lambda:checked(save))


@router.post('/{identity}/availability')
async def availability(identity:str,request:Request):
    payload=await body(request,AvailabilityBody)
    def change():
        try:
            return store(request).set_active(identity,payload.revision,payload.active)
        except ModelConflict as exc:
            raise HTTPException(409,str(exc)) from None
    return await run_in_threadpool(lambda:checked(change))
