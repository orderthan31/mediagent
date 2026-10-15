import json

import httpx
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.auth_routes import require_session
from app.core.config import settings
from video_service.llm_settings import LLMSettingsStore, SettingsConflict
from video_service.llm_providers import PROVIDERS, STT_MODELS, provider_headers, valid_model


def authorize(request: Request):
    session = require_session(request) if request.app.state.auth.store else None
    request.state.settings_owner = session['user']['id'] if session else None
    origin = request.headers.get('origin')
    allowed = [*request.app.state.cors_origins, str(request.base_url).rstrip('/')]
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin not in allowed):
        raise HTTPException(403, '허용되지 않은 설정 요청입니다.')


router = APIRouter(prefix='/api/settings', dependencies=[Depends(authorize)])


class StorageCleanupRequest(BaseModel):
    mode: Literal['temporary', 'jobs']
    job_ids: list[str] = Field(min_length=1, max_length=100)


@router.get('/storage')
def get_storage(request: Request):
    from app.services.storage_settings import inventory
    try:
        return inventory(settings, request.state.settings_owner)
    except (OSError, ValueError):
        raise HTTPException(503, '저장 공간을 확인하지 못했습니다. 잠시 후 다시 조회하세요.') from None


@router.post('/storage/cleanup')
def clean_storage(payload: StorageCleanupRequest, request: Request):
    import re
    from app.services.storage_settings import cleanup
    if len(set(payload.job_ids)) != len(payload.job_ids) or any(not re.fullmatch('[0-9a-f]{32}', value) for value in payload.job_ids):
        raise HTTPException(422, '작업 ID를 확인하세요.')
    return cleanup(settings, request.state.settings_owner, payload.job_ids, payload.mode)


@router.get('/llm')
def get_settings(request: Request):
    try:
        return LLMSettingsStore(settings.storage_root).public(request.state.settings_owner)
    except Exception:
        raise HTTPException(503, '저장된 설정을 읽지 못했습니다. 서버 설정 저장소를 확인하세요.') from None


@router.put('/llm')
async def save_settings(request: Request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'JSON 요청이 필요합니다.')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413, '설정 요청이 너무 큽니다.')
    try:
        payload = json.loads(raw)
        return LLMSettingsStore(settings.storage_root).update(request.state.settings_owner, payload)
    except SettingsConflict:
        raise HTTPException(409, '설정이 변경되었습니다. 새로 불러온 뒤 저장하세요.') from None
    except (ValueError, TypeError):
        raise HTTPException(422, '모델명, 폴백 설정 또는 API 키 형식을 확인하세요.') from None
    except Exception:
        raise HTTPException(503, '설정을 저장하지 못했습니다.') from None


@router.get('/llm/models')
async def list_models(request: Request, provider: str = 'gemini'):
    if provider not in PROVIDERS:
        raise HTTPException(422, '지원하지 않는 공급자입니다.')
    try:
        key = LLMSettingsStore(settings.storage_root).resolve(request.state.settings_owner)['api_keys'][provider]
        if not key:
            raise HTTPException(409, '먼저 해당 공급자의 API 키를 등록하세요.')
        models = []
        token = None
        async with httpx.AsyncClient(timeout=15) as client:
            for _ in range(10):
                params = ({'pageSize': 100, **({'pageToken': token} if token else {})} if provider == 'gemini' else
                          {'limit': 100, **({'after_id': token} if token else {})} if provider == 'anthropic' else {})
                response = await client.get(PROVIDERS[provider]['models_url'],
                    headers=provider_headers(provider, key), params=params)
                if response.status_code in (400, 401, 403):
                    raise HTTPException(422, 'API 키 또는 모델 조회 권한을 확인하세요.')
                response.raise_for_status()
                data = response.json()
                for item in data.get('models' if provider == 'gemini' else 'data', []):
                    name = item.get('name', '').removeprefix('models/') if provider == 'gemini' else item.get('id', '')
                    if provider == 'gemini' and 'generateContent' not in item.get('supportedGenerationMethods', []):
                        continue
                    if provider == 'openrouter' and ('structured_outputs' not in item.get('supported_parameters', []) or
                            'text' not in item.get('architecture', {}).get('output_modalities', [])):
                        continue
                    if valid_model(provider, name):
                        models.append(name)
                token = data.get('nextPageToken') if provider == 'gemini' else data.get('last_id') if provider == 'anthropic' and data.get('has_more') else None
                if not token:
                    break
        return {'models': sorted(set(models))}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, '공급자 모델 목록을 가져오지 못했습니다. 모델명은 직접 입력할 수 있습니다.') from None


@router.get('/llm/stt-models')
def stt_models():
    return {'providers': STT_MODELS}


async def serving_json(request, limit=8192):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'JSON 요청이 필요합니다.')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, '요청이 너무 큽니다.')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, 'JSON 형식을 확인하세요.') from None


@router.get('/node-catalog')
def get_node_catalog():
    from video_service.node_contracts import node_catalog
    return node_catalog()


@router.post('/node-validation')
async def check_node(request: Request):
    from video_service.node_contracts import validate_node
    payload = await serving_json(request)
    try:
        return validate_node(payload)
    except (ValueError, TypeError):
        raise HTTPException(422, '노드·필수 입력 유형·옵션 조합을 확인하세요. 번인에는 자막 입력이 필요합니다.') from None


@router.get('/serving')
def get_serving(request: Request):
    from video_service.serving import serving_settings
    try:
        return serving_settings(settings.storage_root, request.state.settings_owner)
    except Exception:
        raise HTTPException(503, '서빙 설정을 읽지 못했습니다. 기존 설정 저장소·암호화키를 확인하세요.') from None


@router.put('/serving')
async def update_serving(request: Request):
    from video_service.serving import save_serving
    payload = await serving_json(request)
    try:
        return save_serving(settings.storage_root, request.state.settings_owner, payload)
    except SettingsConflict:
        raise HTTPException(409, '설정이 변경되었습니다. 새로 불러온 뒤 Worker 설정을 다시 선택하세요.') from None
    except (ValueError, TypeError):
        raise HTTPException(422, '지원 공급자·모델·서로 다른 폴백을 확인하세요. 전사 Anthropic·임의 STT 모델·키 변경은 지원하지 않습니다.') from None
    except Exception:
        raise HTTPException(503, '서빙 설정을 저장하지 못했습니다. 입력은 유지됩니다.') from None


def definition_response(action):
    from video_service.workflow_definitions import DefinitionConflict
    try:
        return action()
    except FileNotFoundError:
        raise HTTPException(404, '이 계정의 저장된 편집 정의가 없습니다.') from None
    except DefinitionConflict:
        raise HTTPException(409, '다른 편집이 저장되었습니다. 현재 편집은 유지됩니다. 명시적으로 서버값을 다시 불러온 뒤 편집하세요.') from None
    except json.JSONDecodeError:
        raise HTTPException(503, '저장된 편집 정의를 읽지 못했습니다.') from None
    except (ValueError, TypeError):
        raise HTTPException(422, '이름·revision·노드/연결·필수입력·옵션/배치를 확인하고 서버 검증 문제를 해결하세요.') from None
    except Exception:
        raise HTTPException(503, '편집 정의 저장소에 접근하지 못했습니다. 현재 편집은 유지됩니다.') from None


@router.get('/workflow-definitions')
def list_definitions(request: Request):
    from video_service.workflow_definitions import DefinitionStore
    return definition_response(lambda: {'definitions': DefinitionStore(settings.storage_root, request.state.settings_owner).list()})


@router.post('/workflow-definitions/validate')
async def validate_definition(request: Request):
    from video_service.workflow_graph import validate_graph
    return validate_graph(await serving_json(request, limit=131072))


@router.get('/workflow-definitions/{identity}')
def read_definition(identity: str, request: Request):
    from video_service.workflow_definitions import DefinitionStore
    return definition_response(lambda: DefinitionStore(settings.storage_root, request.state.settings_owner).get(identity))


@router.put('/workflow-definitions/{identity}')
async def write_definition(identity: str, request: Request):
    from video_service.workflow_definitions import DefinitionStore
    payload = await serving_json(request, limit=131072)
    return definition_response(lambda: DefinitionStore(settings.storage_root, request.state.settings_owner).save(identity, payload))


from app.api.workflow_ticket_routes import router as workflow_ticket_router
router.include_router(workflow_ticket_router)
from app.api.graph_ticket_routes import router as graph_ticket_router
router.include_router(graph_ticket_router)
from app.api.review_ticket_routes import router as review_ticket_router
router.include_router(review_ticket_router)
from app.api.decision_ticket_routes import router as decision_ticket_router
router.include_router(decision_ticket_router)
