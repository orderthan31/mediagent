"""Opt-in PostgreSQL API. Does not import legacy settings, migrate or start workers.

Construct create_app(database, allowed_origins=(...), secure_cookies=True) explicitly.
There is deliberately no module-level app or implicit DATABASE_URL discovery.
"""
import hmac
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
import psycopg
from starlette.middleware.trustedhost import TrustedHostMiddleware

from video_service.auth import LoginThrottled
from video_service.model_endpoints import PROVIDERS
from video_service.postgres import Conflict, Missing
from video_service.postgres.accounts import Accounts
from video_service.postgres.registry import Registry


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Credentials(Body):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)


class Connection(Body):
    revision: StrictInt = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    protocol: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=2048)


class Compatibility(Body):
    connection_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    connection_revision: StrictInt | None = Field(default=None, ge=1)
    model: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=80)


class Model(Body):
    revision: StrictInt = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    connection_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    connection_revision: StrictInt = Field(ge=1)
    uses: list[str] = Field(min_length=1, max_length=8)
    provider: str | None = Field(default=None, max_length=80)


class Availability(Body):
    revision: StrictInt = Field(ge=1)
    active: StrictBool


class JsonBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS'):
            return await self.app(scope, receive, send)
        size, messages = 0, []
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > 65536:
                return await JSONResponse({'detail': '요청 크기 초과'}, status_code=413,
                                          headers={'Cache-Control': 'no-store'})(scope, receive, send)
            messages.append(message)
            if not message.get('more_body'):
                break
        async def replay():
            return messages.pop(0) if messages else await receive()
        await self.app(scope, replay, send)


def create_app(database, *, allowed_origins, secure_cookies=True):
    origins = frozenset(allowed_origins)
    if not origins or any(urlsplit(value).scheme not in ('http', 'https') or
                          not urlsplit(value).hostname or urlsplit(value).path or
                          urlsplit(value).query or urlsplit(value).fragment or
                          urlsplit(value).username is not None or '*' in value for value in origins):
        raise ValueError('명시적인 same-origin 주소가 필요합니다.')
    app = FastAPI(title='mideagent renewal API', version='0.1.0', docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list({urlsplit(value).hostname for value in origins}))
    app.add_middleware(JsonBodyLimit)
    accounts, registry = Accounts(database), Registry(database)
    cookie = '__Host-mideagent_session' if secure_cookies else 'mideagent_session_dev'

    @app.middleware('http')
    async def request_boundary(request, call_next):
        origin = request.headers.get('origin')
        if origin is not None and origin not in origins:
            return JSONResponse({'detail': '허용되지 않은 요청 origin'}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            # Logout has no request body in the existing client; session CSRF still applies.
            if request.url.path != '/api/auth/logout':
                return JSONResponse({'detail': 'JSON 요청이 필요합니다.'}, status_code=415,
                                    headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=404)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({'detail': '관리자 권한이 필요합니다.'}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def schema_error(request, exc):
        # Pydantic's default error payload can echo password or unknown secret fields.
        return JSONResponse({'detail': '입력 형식 또는 필수 항목을 확인하세요.'}, status_code=422)

    @app.exception_handler(LoginThrottled)
    async def throttled(request, exc):
        return JSONResponse({'detail': '로그인 요청이 너무 많습니다.'}, status_code=429,
                            headers={'Retry-After': str(exc.retry_after)})

    @app.exception_handler(psycopg.Error)
    async def unavailable(request, exc):
        return JSONResponse({'detail': '데이터베이스 요청 실패. 관리자에게 확인해 주세요.'}, status_code=503,
                            headers={'Cache-Control': 'no-store'})

    def session(request: Request):
        value = accounts.session(request.cookies.get(cookie))
        if not value:
            raise HTTPException(401, '로그인이 필요합니다.')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            provided = request.headers.get('x-csrf-token', '')
            if not hmac.compare_digest(provided, value['csrf_token']):
                raise HTTPException(403, '세션 요청 토큰이 일치하지 않습니다.')
        return value

    def administrator(value=Depends(session)):
        if value['user']['role'] != 'admin':
            raise HTTPException(403, '관리자 권한이 필요합니다.')
        return value

    @app.get('/api/auth/session')
    def current(request: Request):
        value = accounts.session(request.cookies.get(cookie))
        return {'enabled': True, 'backend': 'postgres', 'setup_required': accounts.setup_required(),
                'user': value['user'] if value else None, 'csrf_token': value['csrf_token'] if value else None}

    @app.post('/api/auth/bootstrap', status_code=201)
    def bootstrap(body: Credentials, request: Request):
        accounts.throttle('bootstrap:' + (request.client.host if request.client else 'unknown'))
        user = accounts.create(body.username, body.password, first=True)
        return {'user': user, 'setup_required': False}

    @app.post('/api/auth/login')
    def login(body: Credentials, request: Request, response: Response):
        value = accounts.login(body.username, body.password, request.client.host if request.client else 'unknown')
        if not value:
            raise HTTPException(401, '아이디 또는 비밀번호가 일치하지 않습니다.')
        response.set_cookie(cookie, value['token'], max_age=28800, path='/', httponly=True,
                            secure=secure_cookies, samesite='strict')
        return {'enabled': True, 'backend': 'postgres', 'setup_required': False,
                'user': value['user'], 'csrf_token': value['csrf_token']}

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request, response: Response, value=Depends(session)):
        accounts.logout(request.cookies[cookie])
        response.delete_cookie(cookie, path='/', secure=secure_cookies, httponly=True, samesite='strict')

    @app.get('/api/accounts')
    def list_accounts(value=Depends(administrator)):
        return {'accounts': accounts.list(), 'currentId': value['user']['id']}

    @app.post('/api/accounts', status_code=201)
    def issue_account(body: Credentials, value=Depends(administrator)):
        return accounts.create(body.username, body.password, actor_id=value['user']['id'])

    @app.get('/api/capabilities')
    def capabilities(value=Depends(session)):
        return {'backend': 'postgres', 'features': ['accounts', 'serving_connections', 'registered_models'],
                'execution_enabled': False, 'model_network_enabled': False}

    @app.get('/api/settings/serving-connections')
    def connections(value=Depends(session)):
        return {'connections': registry.connections(value['user']['id']), 'providers': PROVIDERS}

    @app.put('/api/settings/serving-connections/{identity}')
    def save_connection(identity: str, body: Connection, value=Depends(session)):
        return registry.save_connection(value['user']['id'], identity, **body.model_dump())

    @app.get('/api/settings/registered-models')
    def models(value=Depends(session)):
        return {'models': registry.models(value['user']['id']), 'providers': PROVIDERS}

    @app.post('/api/settings/registered-models/compatibility')
    def compatibility(body: Compatibility, value=Depends(session)):
        return registry.compatibility(value['user']['id'], body.connection_id, body.connection_revision)

    @app.put('/api/settings/registered-models/{identity}')
    def save_model(identity: str, body: Model, value=Depends(session)):
        data = body.model_dump(exclude={'provider'})
        return registry.save_model(value['user']['id'], identity, **data)

    @app.post('/api/settings/registered-models/{identity}/availability')
    def availability(identity: str, body: Availability, value=Depends(session)):
        return registry.availability(value['user']['id'], identity, **body.model_dump())

    return app
