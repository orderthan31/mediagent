"""Explicit opt-in namespace; same work factory, no queue/legacy migration."""
from fastapi import APIRouter, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from . import work_ticket_routes as work
from .workflow_ticket_routes import body, verify_input

router=APIRouter(prefix='/recovery-tickets')
# Reuse the established work API operations while selecting the owner-scoped
# recovery store only from this server-installed namespace, never a body flag.
for route in work.router.routes:
    if not isinstance(route,APIRoute):continue
    router.add_api_route(route.path.removeprefix('/work-tickets'),route.endpoint,
                         methods=sorted(route.methods),status_code=route.status_code,
                         name='recovery_'+route.name)


class CancelRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=work.UUID4)
    control_revision:int=Field(strict=True,ge=0)


class RecoveryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=work.UUID4)
    revision:int=Field(strict=True,ge=1)
    risk_confirmed:bool=Field(default=False,strict=True)


@router.post('/{identity}/cancel')
async def cancel(identity:str,request:Request):
    payload=await body(request,CancelRequest)
    return await run_in_threadpool(lambda:work.respond(lambda:work.store(request).cancel(identity,payload.control_revision,payload.request_id)))


@router.post('/{identity}/recover',status_code=201)
async def recover(identity:str,request:Request):
    payload=await body(request,RecoveryRequest)
    def create():
        store=work.store(request)
        source=verify_input(request,store.get(identity))
        work.capacity(524288)
        return store.fork(identity,payload.request_id,payload.revision,source,risk_confirmed=payload.risk_confirmed,capacity_check=work.capacity)
    return await run_in_threadpool(lambda:work.respond(create))
