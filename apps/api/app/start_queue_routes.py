"""Normal authenticated owner queue controls and existing-API lifecycle wakeups."""
import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool

from mideagent_orchestrator.start_queue import StartQueue
from mideagent_orchestrator.start_queue_progress import StartQueuePump, advance_start_queue
from video_service.object_store import ObjectStoreError
from video_service.start_queue_policy import QueueConflict, QueueMissing, QueueUnavailable


class QueuePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: StrictInt = Field(ge=0, le=9007199254740991)
    paused: StrictBool | None = None
    order: list[Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]] | None = Field(default=None, max_length=1000)


def queue_request(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except QueueConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except QueueMissing as exc:
        raise HTTPException(404, str(exc)) from None
    except QueueUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except ObjectStoreError as exc:
        status = 403 if exc.status == 403 else 503
        detail = '대기열 저장소에 접근할 수 없습니다.' if status == 403 else '대기열 요청 결과를 확인하지 못했습니다. 다시 확인하세요.'
        if exc.code:
            detail = exc.code + ': ' + detail
        raise HTTPException(status, detail) from None
    except OSError:
        raise HTTPException(503, '대기열 요청 결과를 확인하지 못했습니다. 다시 확인하세요.') from None


def mount_start_queue(app, runtime, session_dependency, *, dispatch_exact, enabled):
    queue = StartQueue(runtime)
    pump = StartQueuePump(runtime, dispatch_exact)
    app.state.start_queue_progress = 'checking' if enabled else 'disabled'

    def advance_owner(owner):
        if not enabled:
            return True
        confirmed = advance_start_queue(runtime, owner, dispatch_exact)
        app.state.start_queue_progress = 'ready' if confirmed else 'unconfirmed'
        return confirmed

    @app.get('/api/queue')
    def get_queue(actor=session_dependency):
        state = queue_request(queue.get, actor['user']['id'])
        return {**state, 'progression': app.state.start_queue_progress}

    @app.patch('/api/queue')
    def patch_queue(body: QueuePatch, actor=session_dependency):
        owner = actor['user']['id']
        state = queue_request(queue.patch, owner, **body.model_dump())
        if not state['paused'] and not advance_owner(owner):
            raise HTTPException(503, '대기열 변경은 저장했지만 시작 상태를 확인하지 못했습니다. 다시 확인하세요.')
        return {**queue_request(queue.get, owner), 'progression': app.state.start_queue_progress}

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def queue_lifespan(application):
        async with previous_lifespan(application) as state:
            if not enabled:
                yield state
                return
            stop = asyncio.Event()

            async def wakeup():
                while not stop.is_set():
                    confirmed = await run_in_threadpool(pump.tick)
                    app.state.start_queue_progress = 'ready' if confirmed else 'unconfirmed'
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=4)
                    except TimeoutError:
                        pass

            task = asyncio.create_task(wakeup())
            try:
                yield state
            finally:
                stop.set()
                await task

    app.router.lifespan_context = queue_lifespan
    return advance_owner
