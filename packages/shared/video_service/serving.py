"""Serving views over the exact settings consumed by the existing media Worker."""
from .llm_settings import LLMSettingsStore
from .llm_providers import PROVIDERS, STT_MODELS


def serving_settings(root, owner=None):
    preferences = LLMSettingsStore(root).public(owner)
    workers = {}
    for role in ('transcription', 'translation'):
        provider = preferences[role + '_provider']
        fallback = preferences[role + '_fallback_provider']
        workers[role] = {'provider': provider, 'model': preferences[role + '_model'],
                         'fallback_provider': fallback, 'fallback_model': preferences[role + '_fallback_model'],
                         'credential': preferences['credentials'][provider],
                         'fallback_credential': preferences['credentials'][fallback],
                         'credential_provider': provider, 'fallback_credential_provider': fallback,
                         'connection': 'unverified'}
    return {'revision': preferences['revision'], 'workers': workers,
            'fallback_on_error': preferences['fallback_on_error'], 'fallback_on_block': preferences['fallback_on_block'],
            'providers': {k: v['label'] for k, v in PROVIDERS.items()}, 'stt_models': STT_MODELS,
            'runtime': {'process': 'media_worker.worker:Worker', 'connection': 'unverified',
                        'notice': '논리 처리 역할별 설정입니다. 저장·키 보유·지원 모델은 Worker 연결이나 추론 성공을 뜻하지 않습니다.'},
            'fixed_workers': [{'id': 'media', 'provider': 'FFmpeg/FFprobe', 'model': None, 'editable': False,
                               'reason': '영상 분석·오디오 추출·자막 생성·번인/인코딩은 기존 로컬 실행기를 사용합니다.'},
                              {'id': 'faceswap', 'provider': 'FaceFusion', 'model': None, 'editable': False,
                               'reason': '엔진/모델은 Worker 실행 환경에서 지정합니다. 이 화면은 모델을 내려받거나 Worker를 시작하지 않습니다.'}]}


def save_serving(root, owner, payload):
    expected = {'revision', 'workers', 'fallback_on_error', 'fallback_on_block'}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError('revision·두 Worker 역할·공유 폴백 정책이 필요합니다. 키 변경은 기존 설정 화면을 사용하세요.')
    workers = payload['workers']
    if not isinstance(workers, dict) or set(workers) != {'transcription', 'translation'}:
        raise ValueError('현재 지정 가능한 Worker 역할은 전사와 번역입니다.')
    translated = {key: payload[key] for key in ('revision', 'fallback_on_error', 'fallback_on_block')}
    for role, config in workers.items():
        if not isinstance(config, dict) or set(config) != {'provider', 'model', 'fallback_provider', 'fallback_model'}:
            raise ValueError('공급자·모델·폴백 공급자/모델 형식을 확인하세요.')
        if any(not isinstance(config[key], str) or config[key] not in PROVIDERS for key in ('provider', 'fallback_provider')):
            raise ValueError('지원하지 않는 공급자입니다.')
        if role == 'transcription' and any(config[key] not in STT_MODELS for key in ('provider', 'fallback_provider')):
            raise ValueError('전사는 Gemini/OpenAI/xAI/OpenRouter만 지원합니다. Anthropic 전사는 지원하지 않습니다.')
        for key, value in config.items():
            translated[role + '_' + key] = value
    # Existing update owns locking/revision, validation, encrypted-key preservation and atomic writes.
    LLMSettingsStore(root).update(owner, translated)
    return serving_settings(root, owner)
