"""Endpoint metadata and an injected-transport, text-only OpenAI contract.

No default network transport or environment credential lookup is provided. The
renewal API only stores configuration; it never calls this adapter on save/check.
A deployment must separately supply an operator-approved, address-pinned transport
before enabling real model calls. MockTransport exercises the exact wire contract.
"""
import ipaddress
import json
import re
from urllib.parse import urlsplit

import httpx

PROVIDERS = {'openai_compatible': 'Custom OpenAI-compatible · 로컬/사설', 'openai': 'OpenAI',
             'gemini': 'Google Gemini', 'anthropic': 'Anthropic Claude', 'xai': 'Grok (xAI)'}
FRONTIER_CONNECTIONS = {
    'openai': ('openai', 'https://api.openai.com/v1'),
    'gemini': ('gemini', 'https://generativelanguage.googleapis.com/v1beta'),
    'anthropic': ('anthropic', 'https://api.anthropic.com'),
    'xai': ('openai', 'https://api.x.ai/v1'),
}
# Implemented adapter capabilities, not a model-name heuristic or a live probe.
PROTOCOL_USES = {'openai_compatible': ['translation', 'transcription'], 'openai': ['translation', 'transcription'],
                 'gemini': ['translation', 'transcription'], 'anthropic': []}


def validate_endpoint(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError('API 기본 주소가 필요합니다.')
    if re.search(r'[\s\\%?#]', value):
        raise ValueError('주소에 공백·인증정보·query·fragment·인코딩 경로를 넣을 수 없습니다.')
    try:
        url = urlsplit(value)
        port = url.port
        host = url.hostname
    except ValueError:
        raise ValueError('올바른 API 기본 주소를 입력하세요.') from None
    if url.scheme not in ('http', 'https') or not host or url.username is not None or url.password is not None:
        raise ValueError('인증정보 없는 HTTP(S) API 주소를 입력하세요.')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('주소의 포트가 올바르지 않습니다.')
    if not host.isascii() or not re.fullmatch(r'[A-Za-z0-9.:-]+', host):
        raise ValueError('호스트 이름이 올바르지 않습니다.')
    if not re.fullmatch(r'[/A-Za-z0-9._~-]*', url.path) or any(p in ('.', '..') for p in url.path.split('/')):
        raise ValueError('API 기본 경로가 올바르지 않습니다.')
    if host.lower().rstrip('.') in ('metadata.google.internal', 'metadata', 'instance-data'):
        raise ValueError('메타데이터 주소는 등록할 수 없습니다.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_link_local or address.is_multicast or address.is_unspecified):
        raise ValueError('메타데이터·링크로컬·멀티캐스트 주소는 등록할 수 없습니다.')
    # Registration allows intended local/on-prem addresses; it does not grant egress.
    return value.rstrip('/')


def canonical_hash(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def connection_contract(provider, protocol=None, endpoint=None, *, previous=None):
    """Pin new named connections server-side; never rewrite a stored legacy tuple."""
    if provider not in PROVIDERS:
        raise ValueError('지원하는 공급자를 선택하세요.')
    if previous and previous['provider'] == provider and (
        protocol is None or protocol == previous['protocol']
    ) and (endpoint is None or endpoint == previous['endpoint']):
        return previous['protocol'], previous['endpoint']
    if provider in FRONTIER_CONNECTIONS:
        fixed_protocol, fixed_endpoint = FRONTIER_CONNECTIONS[provider]
        if (protocol is not None and protocol != fixed_protocol
                or endpoint is not None and endpoint != fixed_endpoint):
            raise ValueError('이 공급자는 서버의 공식 주소·프로토콜을 사용합니다. 별도 주소는 Custom 연결로 등록하세요.')
        return fixed_protocol, fixed_endpoint
    protocol = protocol or 'openai_compatible'
    if protocol not in PROTOCOL_USES:
        raise ValueError('지원하는 프로토콜을 선택하세요.')
    return protocol, validate_endpoint(endpoint)


class EndpointFailure(RuntimeError):
    """Sanitized failure: raw upstream errors/responses never become API errors."""

    def __init__(self, message, *, code='invalid_response'):
        super().__init__(message)
        self.code = code


class OpenAITextAdapter:
    def __init__(self, endpoint, *, transport, approved_origins, api_key=None):
        self.endpoint = validate_endpoint(endpoint)
        origin = urlsplit(self.endpoint)
        identity = f'{origin.scheme}://{origin.netloc}'
        if identity not in approved_origins or transport is None:
            raise ValueError('승인된 transport와 origin이 필요합니다.')
        if api_key is not None and (not isinstance(api_key, str) or not 1 <= len(api_key) <= 4096
                                    or '\r' in api_key or '\n' in api_key):
            raise ValueError('인증정보 형식 오류')
        self._key = api_key
        self._client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                                    timeout=30.0, headers={'Authorization': 'Bearer ' + api_key} if api_key else {})

    def close(self):
        self._client.close()

    def _request(self, method, suffix, payload=None, *, data=None, files=None):
        try:
            with self._client.stream(method, self.endpoint + suffix, json=payload, data=data, files=files) as response:
                if response.status_code != 200:
                    code = ('rate_limited' if response.status_code == 429 else
                            'upstream_failure' if response.status_code >= 500 else
                            'authentication_failed' if response.status_code in (401, 403) else
                            'request_rejected')
                    raise EndpointFailure('모델 서버 요청 실패 · 자동 재시도하지 않습니다.', code=code)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 262144:
                        raise EndpointFailure('모델 서버 응답 크기 초과')
            value = json.loads(body)
            stack = [(value, 0)]
            count = 0
            while stack:
                item, depth = stack.pop()
                count += 1
                if depth > 20 or count > 10000:
                    raise EndpointFailure('모델 서버 응답 구조 초과')
                if isinstance(item, str) and self._key and self._key in item:
                    raise EndpointFailure('모델 서버 응답에 인증정보가 포함되어 거절했습니다.')
                if isinstance(item, dict):
                    stack.extend((v, depth + 1) for pair in item.items() for v in pair)
                elif isinstance(item, list):
                    stack.extend((v, depth + 1) for v in item)
            return value
        except EndpointFailure:
            raise
        except httpx.HTTPError:
            raise EndpointFailure('모델 서버 통신 결과 불명 · 자동 재시도하지 않습니다.', code='outcome_unknown') from None
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise EndpointFailure('모델 서버 통신 또는 응답 형식 오류 · 자동 재시도하지 않습니다.') from None

    def models(self):
        value = self._request('GET', '/models')
        data = value.get('data') if isinstance(value, dict) else None
        if not isinstance(data, list) or len(data) > 1000 or any(
                not isinstance(v, dict) or not isinstance(v.get('id'), str) or not 1 <= len(v['id']) <= 200 for v in data):
            raise EndpointFailure('모델 목록 응답 형식 오류')
        return [v['id'] for v in data]

    def chat(self, model, messages):
        if not isinstance(model, str) or not 1 <= len(model) <= 200:
            raise ValueError('모델 ID가 필요합니다.')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise ValueError('텍스트 메시지는 1~100개여야 합니다.')
        for item in messages:
            if (not isinstance(item, dict) or set(item) != {'role', 'content'}
                    or item['role'] not in ('system', 'user', 'assistant')
                    or not isinstance(item['content'], str) or len(item['content']) > 16000):
                raise ValueError('텍스트 메시지 형식 오류 · 멀티모달은 아직 지원하지 않습니다.')
        if len(json.dumps(messages).encode()) > 131072:
            raise ValueError('요청 크기 초과')
        value = self._request('POST', '/chat/completions', {'model': model, 'messages': messages, 'stream': False})
        try:
            choice = value['choices'][0]
            content = choice['message']['content']
            if choice['finish_reason'] != 'stop' or not isinstance(content, str):
                raise ValueError()
            return content
        except (KeyError, IndexError, TypeError, ValueError):
            raise EndpointFailure('완료된 텍스트 응답이 아닙니다.') from None


class GeminiTextAdapter(OpenAITextAdapter):
    """Native generateContent; key is header-only, no SDK-internal retries."""

    def __init__(self, endpoint, *, transport, approved_origins, api_key=None):
        super().__init__(endpoint, transport=transport, approved_origins=approved_origins, api_key=api_key)
        self._client.headers.pop('Authorization', None)
        if api_key:
            self._client.headers['x-goog-api-key'] = api_key

    def chat(self, model, messages):
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,200}', model):
            raise ValueError('Gemini 모델 ID 형식 오류')
        if (not isinstance(messages, list) or len(messages) != 2
                or [item.get('role') for item in messages] != ['system', 'user']
                or any(not isinstance(item.get('content'), str) or len(item['content']) > 16000 for item in messages)):
            raise ValueError('번역 메시지 형식 오류')
        value = self._request('POST', '/models/' + model + ':generateContent', {
            'systemInstruction': {'parts': [{'text': messages[0]['content']}]},
            'contents': [{'role': 'user', 'parts': [{'text': messages[1]['content']}]}],
        })
        return self.final_text(value)

    @staticmethod
    def final_text(value):
        try:
            feedback = value.get('promptFeedback') if isinstance(value, dict) else None
            if (isinstance(feedback, dict) and feedback.get('blockReason')
                    and feedback['blockReason'] != 'BLOCK_REASON_UNSPECIFIED'):
                raise EndpointFailure('Gemini 요청이 차단되었습니다.', code='request_rejected')
            candidate = value['candidates'][0]
            if candidate['finishReason'] != 'STOP':
                raise EndpointFailure('Gemini 응답이 차단되었거나 미완료입니다.', code='request_rejected')
            parts = candidate['content']['parts']
            if not isinstance(parts, list) or not parts:
                raise ValueError()
            metadata = {'thought', 'thoughtSignature', 'partMetadata', 'mediaResolution',
                        'mediaProcessing', 'audioTranscription', 'speechMetadata', 'videoMetadata'}
            texts = []
            for part in parts:
                if not isinstance(part, dict):
                    raise TypeError()
                # Only final text is translation input, never thoughts, signatures
                # or a Part.data tool/media variant (including ambiguous unions).
                if part.get('thought') is True or 'text' not in part:
                    continue
                if set(part) - ({'text'} | metadata):
                    continue
                if (not isinstance(part['text'], str)
                        or 'thought' in part and type(part['thought']) is not bool):
                    raise ValueError()
                texts.append(part['text'])
            text = ''.join(texts)
            if not text.strip():
                raise ValueError()
            return text
        except (KeyError, IndexError, TypeError, ValueError):
            raise EndpointFailure('완료된 Gemini 텍스트 응답이 아닙니다.') from None


class OpenAIAudioAdapter(OpenAITextAdapter):
    """OpenAI whisper-1 multipart verbose_json with real segment timestamps."""

    def transcribe(self, model, audio, language):
        from .audio_contract import audio_info, timed_segments

        info = audio_info(audio)
        if model != 'whisper-1' or not re.fullmatch(r'auto|[a-z]{2,3}', language):
            raise ValueError('지원되는 whisper-1/언어를 선택하세요.')
        data = {'model': model, 'response_format': 'verbose_json', 'timestamp_granularities[]': 'segment'}
        if language != 'auto':
            data['language'] = language
        value = self._request('POST', '/audio/transcriptions', data=data, files={'file': ('audio.wav', audio, 'audio/wav')})
        try:
            return timed_segments(value['segments'], info['duration_seconds'])
        except (KeyError, TypeError, ValueError):
            raise EndpointFailure('시간 정보가 있는 OpenAI 전사 응답이 아닙니다.') from None


class GeminiAudioAdapter(GeminiTextAdapter):
    """Inline PCM audio + structured timestamp request, not text-only chat."""

    def transcribe(self, model, audio, language):
        import base64

        from .audio_contract import audio_info, timed_segments

        info = audio_info(audio)
        if not re.fullmatch(r'gemini-[A-Za-z0-9._-]{1,190}', model) or not re.fullmatch(r'auto|[a-z]{2,3}', language):
            raise ValueError('지원되는 Gemini 전사 모델/언어를 선택하세요.')
        value = self._request('POST', '/models/' + model + ':generateContent', {
            'systemInstruction': {'parts': [{'text': 'Transcribe the supplied audio, do not translate. Language=' + language + '. Return a JSON array of segments with start/end numeric seconds from the audio beginning and text. Every segment must have actual timestamps within the audio duration. Never invent absent timing. No markdown. Maximum100 segments.'}]},
            'contents': [{'role': 'user', 'parts': [{'inlineData': {'mimeType': 'audio/wav', 'data': base64.b64encode(audio).decode('ascii')}}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'responseSchema': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'properties': {'start': {'type': 'NUMBER'}, 'end': {'type': 'NUMBER'}, 'text': {'type': 'STRING'}}, 'required': ['start', 'end', 'text']}}},
        })
        text = self.final_text(value)
        try:
            return timed_segments(json.loads(text), info['duration_seconds'])
        except (TypeError, ValueError):
            raise EndpointFailure('시간 정보가 있는 Gemini 전사 응답이 아닙니다.') from None
