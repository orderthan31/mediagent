"""Opt-in PostgreSQL API. Does not import legacy settings, migrate or start workers.

Construct create_app(database, allowed_origins=(...), secure_cookies=True) explicitly.
There is deliberately no module-level app or implicit DATABASE_URL discovery.
"""

import hmac
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt
from starlette.middleware.trustedhost import TrustedHostMiddleware
from video_service.auth import LoginThrottled
from video_service.model_endpoints import PROVIDERS
from video_service.postgres import Conflict, Missing
from video_service.postgres.accounts import Accounts
from video_service.postgres.registry import Registry
from video_service.postgres.sources import Sources


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Credentials(Body):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)


class Connection(Body):
    revision: StrictInt = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    protocol: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=2048)


class ProviderCredential(Body):
    revision: StrictInt = Field(ge=1)
    secret: SecretStr | None


class Compatibility(Body):
    connection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    connection_revision: StrictInt | None = Field(default=None, ge=1)
    model: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=80)


class Model(Body):
    revision: StrictInt = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    connection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    connection_revision: StrictInt = Field(ge=1)
    model_types: list[str] = Field(min_length=1, max_length=9)
    input_modalities: list[str] = Field(min_length=1, max_length=5)
    output_modalities: list[str] = Field(min_length=1, max_length=5)
    capabilities: list[str] = Field(min_length=1, max_length=8)
    provider: str | None = Field(default=None, max_length=80)


class Availability(Body):
    revision: StrictInt = Field(ge=1)
    active: StrictBool


class AgentConfiguration(Body):
    revision: StrictInt = Field(ge=0)
    enabled: StrictBool
    replicas: StrictInt = Field(ge=0, le=8)


class SourceMetadata(Body):
    filename: str = Field(min_length=1, max_length=255)
    artifact_ref: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    byte_count: StrictInt = Field(ge=0, le=9223372036854775807)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=40)
    duration_seconds: float | None = Field(
        default=None, ge=0, le=31536000, allow_inf_nan=False
    )


class JsonBodyLimit:
    def __init__(self, app, *, uploads=False):
        self.app = app
        self.uploads = uploads

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        binary = (
            self.uploads
            and scope["method"] == "PUT"
            and re.fullmatch(r"/api/video-uploads/[a-f0-9]{32}/chunks", scope["path"])
        )
        limit = 4194304 if binary else 65536
        size, messages = 0, []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > limit:
                return await JSONResponse(
                    {"detail": "요청 크기 초과"},
                    status_code=413,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body"):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


def create_app(
    database,
    *,
    allowed_origins,
    secure_cookies=True,
    content_store=None,
    local_execution=False,
    agent_executor=None,
    cpu_driver=None,
    broker_factory=None,
    credential_store=None,
):
    origins = frozenset(allowed_origins)
    if not origins or any(
        urlsplit(value).scheme not in ("http", "https")
        or not urlsplit(value).hostname
        or urlsplit(value).path
        or urlsplit(value).query
        or urlsplit(value).fragment
        or urlsplit(value).username is not None
        or "*" in value
        for value in origins
    ):
        raise ValueError("명시적인 same-origin 주소가 필요합니다.")
    from video_service.postgres.fleet import Fleet

    if broker_factory is not None and (
        not local_execution
        or getattr(content_store, "storage_kind", None) != "s3"
        or cpu_driver is not None
        or agent_executor is not None
    ):
        raise ValueError(
            "Broker execution requires explicit CPU approval and exclusive S3 routing"
        )

    if cpu_driver is not None and (
        not local_execution or content_store is None or agent_executor is not None
    ):
        raise ValueError(
            "CPU fleet requires explicit local execution and no competing executor"
        )
    fleet = Fleet(database, cpu_driver)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if cpu_driver is not None:
                fleet.close()

    app = FastAPI(
        title="mideagent renewal API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.agent_fleet = fleet
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list({urlsplit(value).hostname for value in origins}),
    )
    app.add_middleware(JsonBodyLimit, uploads=content_store is not None)
    accounts, registry, sources = (
        Accounts(database),
        Registry(database),
        Sources(database),
    )
    cookie = "__Host-mideagent_session" if secure_cookies else "mideagent_session_dev"

    @app.middleware("http")
    async def request_boundary(request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return JSONResponse(
                {"detail": "허용되지 않은 요청 origin"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        content_type = request.headers.get("content-type", "").split(";")[0].lower()
        binary = (
            content_store is not None
            and request.method == "PUT"
            and re.fullmatch(
                r"/api/video-uploads/[a-f0-9]{32}/chunks", request.url.path
            )
            and content_type == "application/octet-stream"
        )
        # Logout has no request body in the existing client; session CSRF still applies.
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and content_type != "application/json"
            and not binary
            and request.url.path != "/api/auth/logout"
        ):
            return JSONResponse(
                {"detail": "JSON 요청이 필요합니다."},
                status_code=415,
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({"detail": "관리자 권한이 필요합니다."}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def schema_error(request, exc):
        # Pydantic's default error payload can echo password or unknown secret fields.
        return JSONResponse(
            {"detail": "입력 형식 또는 필수 항목을 확인하세요."}, status_code=422
        )

    @app.exception_handler(LoginThrottled)
    async def throttled(request, exc):
        return JSONResponse(
            {"detail": "로그인 요청이 너무 많습니다."},
            status_code=429,
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(psycopg.Error)
    async def unavailable(request, exc):
        return JSONResponse(
            {"detail": "데이터베이스 요청 실패. 관리자에게 확인해 주세요."},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    def session(request: Request):
        value = accounts.session(request.cookies.get(cookie))
        if not value:
            raise HTTPException(401, "로그인이 필요합니다.")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            provided = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(provided, value["csrf_token"]):
                raise HTTPException(403, "세션 요청 토큰이 일치하지 않습니다.")
        return value

    session_dependency = Depends(session)

    def administrator(value=session_dependency):
        if value["user"]["role"] != "admin":
            raise HTTPException(403, "관리자 권한이 필요합니다.")
        return value

    administrator_dependency = Depends(administrator)

    from video_service.postgres.legacy_archive import LegacyArchive

    archive = LegacyArchive(database)

    @app.get("/api/legacy/history")
    def legacy_history(
        kind: str = "job",
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        actor=administrator_dependency,
    ):
        return archive.records(kind=kind, limit=limit, offset=offset)

    @app.get("/api/legacy/summary")
    def legacy_summary(actor=administrator_dependency):
        return archive.summary()

    @app.get("/api/auth/session")
    def current(request: Request):
        value = accounts.session(request.cookies.get(cookie))
        return {
            "enabled": True,
            "backend": "postgres",
            "setup_required": accounts.setup_required(),
            "user": value["user"] if value else None,
            "csrf_token": value["csrf_token"] if value else None,
        }

    @app.post("/api/auth/bootstrap", status_code=201)
    def bootstrap(body: Credentials, request: Request):
        accounts.throttle(
            "bootstrap:" + (request.client.host if request.client else "unknown")
        )
        user = accounts.create(body.username, body.password, first=True)
        return {"user": user, "setup_required": False}

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        value = accounts.login(
            body.username,
            body.password,
            request.client.host if request.client else "unknown",
        )
        if not value:
            raise HTTPException(401, "아이디 또는 비밀번호가 일치하지 않습니다.")
        response.set_cookie(
            cookie,
            value["token"],
            max_age=28800,
            path="/",
            httponly=True,
            secure=secure_cookies,
            samesite="strict",
        )
        return {
            "enabled": True,
            "backend": "postgres",
            "setup_required": False,
            "user": value["user"],
            "csrf_token": value["csrf_token"],
        }

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response, value=session_dependency):
        accounts.logout(request.cookies[cookie])
        response.delete_cookie(
            cookie, path="/", secure=secure_cookies, httponly=True, samesite="strict"
        )

    @app.get("/api/accounts")
    def list_accounts(value=administrator_dependency):
        return {"accounts": accounts.list(), "currentId": value["user"]["id"]}

    @app.post("/api/accounts", status_code=201)
    def issue_account(body: Credentials, value=administrator_dependency):
        return accounts.create(
            body.username, body.password, actor_id=value["user"]["id"]
        )

    @app.get("/api/capabilities")
    def capabilities(value=session_dependency):
        features = [
            "accounts",
            "serving_connections",
            "registered_models",
            "source_metadata",
        ]
        if content_store is not None:
            features += [
                "verified_uploads",
                "workflows",
                "jobs",
                "node_runs",
                "review_gates",
                "execution_consent",
            ]
        features += ["admin_access", "agent_management"]
        return {
            "backend": "postgres",
            "features": features,
            "agent_runtime": (
                "amqp_explicit"
                if broker_factory is not None
                else "cpu_subprocess"
                if cpu_driver is not None
                else None
            ),
            "execution_enabled": content_store is not None and local_execution,
            "model_network_enabled": False,
            "db_credentials_enabled": credential_store is not None,
            "transport": (
                "explicit_amqp"
                if broker_factory is not None
                else "explicit_cpu_subprocess"
                if content_store is not None
                else None
            ),
        }

    @app.get("/api/settings/serving-connections")
    def connections(value=administrator_dependency):
        return {
            "connections": registry.connections(value["user"]["id"]),
            "providers": PROVIDERS,
        }

    @app.put("/api/settings/serving-connections/{identity}")
    def save_connection(
        identity: str, body: Connection, value=administrator_dependency
    ):
        return registry.save_connection(
            value["user"]["id"], identity, **body.model_dump()
        )

    @app.put("/api/settings/serving-connections/{identity}/credential")
    def provider_credential(
        identity: str, body: ProviderCredential, value=administrator_dependency
    ):
        if credential_store is None:
            raise HTTPException(503, "credential_store_unavailable")
        return credential_store.save(
            value["user"]["id"],
            identity,
            revision=body.revision,
            secret=body.secret.get_secret_value() if body.secret is not None else None,
        )

    @app.get("/api/settings/registered-models")
    def models(value=administrator_dependency):
        return {"models": registry.models(value["user"]["id"]), "providers": PROVIDERS}

    @app.post("/api/settings/registered-models/compatibility")
    def compatibility(body: Compatibility, value=administrator_dependency):
        return registry.compatibility(
            value["user"]["id"], body.connection_id, body.connection_revision
        )

    @app.put("/api/settings/registered-models/{identity}")
    def save_model(identity: str, body: Model, value=administrator_dependency):
        data = body.model_dump(exclude={"provider"})
        return registry.save_model(value["user"]["id"], identity, **data)

    @app.post("/api/settings/registered-models/{identity}/availability")
    def availability(identity: str, body: Availability, value=administrator_dependency):
        return registry.availability(value["user"]["id"], identity, **body.model_dump())

    @app.get("/api/source-metadata")
    def source_list(
        page: int = Query(default=1, ge=1, le=1000000),
        page_size: int = Query(default=20, ge=1, le=100),
        value=session_dependency,
    ):
        return sources.list(value["user"]["id"], page=page, page_size=page_size)

    @app.get("/api/source-metadata/{identity}")
    def source_detail(identity: str, value=session_dependency):
        return sources.get(value["user"]["id"], identity)

    @app.put("/api/source-metadata/{identity}")
    def source_register(identity: str, body: SourceMetadata, value=session_dependency):
        return sources.register(value["user"]["id"], identity, **body.model_dump())

    @app.get("/api/admin/agents")
    def agent_list(value=administrator_dependency):
        return {"agents": fleet.list()}

    @app.get("/api/admin/agents/{identity}")
    def agent_detail(identity: str, value=administrator_dependency):
        return fleet.get(identity)

    @app.put("/api/admin/agents/{identity}/configuration")
    def agent_configuration(
        identity: str, body: AgentConfiguration, value=administrator_dependency
    ):
        return fleet.configure(value["user"]["id"], identity, **body.model_dump())

    if content_store is not None:
        from video_service.postgres.execution import Execution

        from .renewal_routes import mount_runtime

        mount_runtime(
            app,
            Execution(
                database,
                content_store,
                agent_executor=agent_executor,
                fleet=fleet if cpu_driver is not None else None,
                engine_runtime_enabled=bool(
                    getattr(broker_factory, "engine_factory", None)
                ),
            ),
            session,
            administrator,
            local_execution=local_execution,
            broker_factory=broker_factory,
        )
    elif local_execution:
        raise ValueError("CPU execution requires an explicit private content store")
    return app
