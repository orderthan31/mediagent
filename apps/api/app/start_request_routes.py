"""HTTP boundary and resident lifecycle for explicit durable start requests."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Query
from starlette.concurrency import run_in_threadpool

from mideagent_orchestrator.start_requests import StartRequests


def mount_start_requests(app, runtime, owner_dependency, *, create_model, saved_model,
                         selection_model, selection_plan, enabled, factory):
    capabilities = set(getattr(factory, 'model_role_factories', {}) or {})
    if getattr(factory, 'model_role_factory', None) is not None:
        capabilities.add('transcription')
    service = StartRequests(runtime, enabled=enabled, capabilities=capabilities,
        selection_plan=lambda owner, body: selection_plan(owner, selection_model(
            **{k: v for k, v in body.items() if k not in {'request_id', 'token', 'paid_confirmed'}})))
    service.factory = factory
    app.state.start_requests = service

    # Define concrete routes before dynamic identifiers.
    @app.get('/api/work-entry/start-requests')
    def list_requests(owned=owner_dependency):
        return service.list(owned)

    @app.get('/api/work-entry/start-requests/by-request')
    def lookup_request(request_id: str = Query(min_length=1, max_length=100), owned=owner_dependency):
        return service.by_nonce(owned, request_id)

    @app.get('/api/work-entry/start-requests/{identity}')
    def request_status(identity: str, owned=owner_dependency):
        return service.get(owned, identity)

    @app.post('/api/work-entry/start-requests/{identity}/cancel')
    def cancel_request(identity: str, owned=owner_dependency):
        return service.cancel(owned, identity)

    def create_and_start(body, owned=owner_dependency):
        return service.submit_raw(owned, body.model_dump())

    create_and_start.__annotations__['body'] = create_model
    app.post('/api/work-entry/create-and-start', status_code=202)(create_and_start)

    def saved_start(identity: str, body, owned=owner_dependency):
        return service.submit_saved(owned, identity, body.revision, body.request_id)

    saved_start.__annotations__['body'] = saved_model
    app.post('/api/renewal/jobs/{identity}/start-request', status_code=202)(saved_start)

    @app.get('/api/renewal/jobs/{identity}/start-request')
    def saved_status(identity: str, owned=owner_dependency):
        return service.for_job(owned, identity)

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state:
            if not enabled:
                yield state
                return
            service.stopping.clear()
            stop = asyncio.Event()

            async def consume():
                while not stop.is_set():
                    try:
                        await run_in_threadpool(service.tick)
                    except Exception:
                        # A temporary database outage must not kill residency.
                        import logging
                        logging.getLogger(__name__).warning('start_request_scan_unconfirmed')
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1)
                    except TimeoutError:
                        pass

            task = asyncio.create_task(consume())
            try:
                yield state
            finally:
                # Fence pending mutations immediately, then drain the bounded
                # consumer. Never abandon a thread with permission to commit.
                service.stopping.set()
                stop.set()
                await task

    app.router.lifespan_context = lifespan
