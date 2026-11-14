"""LiteLLM SDK inside the existing model-tool/credential/egress boundary.

One request-owned client, one allowed wire attempt, exact selected remote model.
No Proxy, router, implicit credentials, global user keys or SDK-owned transport.
Historical candidates without an invocation contract do not enter this adapter.
"""
from copy import deepcopy
import importlib.metadata
import io
import json
import logging
import os
import re
from threading import Lock
from urllib.parse import urlsplit

import httpx

from video_service.audio_contract import audio_info, timed_segments
from video_service.llm_contract import SDK_PROTOCOLS, parse_options, validate_operation_options
from video_service.task_console import redact
from .endpoints import EndpointFailure, validate_endpoint
from .sdk_cache import verify as verify_tokenizers

SDK_VERSION = "1.106.6"
MAX_RESPONSE = 262144
_LOAD_LOCK = Lock()


def _sdk():
    # Checked before the lazy import: LiteLLM otherwise fetches a cost map at import.
    if os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() != "true":
        raise EndpointFailure("SDK 오프라인 부트스트랩 설정이 필요합니다.", code="unavailable")
    try:
        verify_tokenizers()
        if importlib.metadata.version("litellm") != SDK_VERSION:
            raise ValueError("unsupported SDK version")
        with _LOAD_LOCK:
            import litellm
            # These are process-wide SDK safety settings, never per-user secrets.
            litellm.suppress_debug_info = True
            for key in ("api_key", "openai_key", "anthropic_key", "gemini_key", "model_fallbacks", "fallbacks", "default_fallbacks", "context_window_fallbacks", "model_alias_map", "headers", "pre_call_rules", "post_call_rules", "cache", "client_session", "aclient_session"):
                if getattr(litellm, key, None):
                    raise ValueError("SDK global credential/client/routing state is not permitted")
            if getattr(litellm, "num_retries", None) not in (None, 0):
                raise ValueError("SDK global retries are not permitted")
            if getattr(litellm, "set_verbose", False) or any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy")):
                raise ValueError("SDK payload debug logging is not permitted")
            callbacks = [item for key in ("callbacks", "success_callback", "failure_callback", "input_callback") for item in (getattr(litellm, key, None) or [])]
            # Gemini registers the SDK's inert local cache marker even with
            # caching=False. It is safe only while the global cache above is None
            # and this request explicitly forbids cache reads/writes.
            if any(type(item) is not str or item != "cache" for item in callbacks) or getattr(litellm, "global_disable_no_log_param", False):
                raise ValueError("SDK global callbacks are not permitted")
        if os.environ.get("EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER"):
            raise ValueError("Alternate SDK transport is not permitted")
        return litellm
    except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
        raise EndpointFailure("검증된 SDK·오프라인 리소스·독립 호출 설정이 필요합니다.", code="unavailable") from None


class _GuardedTransport(httpx.BaseTransport):
    def __init__(self, inner, endpoint, path, key, model, options):
        self.inner, self.expected, self.key = inner, httpx.URL(endpoint + path), key
        self.model = model
        self.options, self.schema = options, None
        self.vertex = '/publishers/google/models/' in self.expected.path
        self.calls, self.failure, self.lock = 0, None, Lock()

    def _fail(self, message, code="request_rejected", *, capacity_exceeded=False):
        error = EndpointFailure(message, code=code, capacity_exceeded=capacity_exceeded)
        if self.failure is None:
            self.failure = error
        raise error

    def handle_request(self, request):
        with self.lock:
            if self.calls:
                self._fail("SDK 내부 재전송을 차단했습니다. 자동 재호출하지 않습니다.", "outcome_unknown")
            if request.method != "POST" or request.url != self.expected:
                self._fail("SDK가 고정된 공급자 요청 주소를 변경해 차단했습니다.")
            content = request.read()
            if len(content) > 3 * 1024 * 1024:
                self._fail("모델 요청 크기 상한을 초과했습니다.")
            if request.url.path.endswith(('/chat/completions', '/v1/messages', '/interactions')):
                try:
                    selected = json.loads(content).get("model")
                except (ValueError, TypeError, AttributeError):
                    self._fail("SDK 모델 요청 형식 오류")
                if selected != self.model:
                    self._fail("SDK가 워크플로우의 선택 모델을 변경해 차단했습니다.")
                if request.url.path.endswith('/interactions') and 'temperature' in self.options:
                    if json.loads(content).get('temperature') != self.options['temperature']:
                        self._fail("선택 모델의 전사 temperature 옵션을 SDK가 보존하지 못했습니다.", "unavailable")
            elif request.url.path.endswith('/audio/transcriptions'):
                from email.parser import BytesParser
                from email.policy import default
                mime = BytesParser(policy=default).parsebytes(b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\nMIME-Version: 1.0\r\n\r\n' + content)
                models = [part.get_payload(decode=True).decode('utf8') for part in mime.iter_parts() if part.get_param('name', header='content-disposition') == 'model']
                if models != [self.model]:
                    self._fail("SDK가 워크플로우의 전사 모델을 변경해 차단했습니다.")
                if 'temperature' in self.options:
                    values = [part.get_payload(decode=True).decode('utf8') for part in mime.iter_parts() if part.get_param('name', header='content-disposition') == 'temperature']
                    try:
                        preserved = len(values) == 1 and float(values[0]) == self.options['temperature']
                    except ValueError:
                        preserved = False
                    if not preserved:
                        self._fail("선택 모델의 전사 temperature 옵션을 SDK가 보존하지 못했습니다.", "unavailable")
            if self.schema is not None:
                self._validate_schema_and_options(json.loads(content))
            if self.vertex and (request.headers.get('authorization') != 'Bearer ' + self.key or any(request.headers.get(k) for k in ('x-api-key', 'x-goog-api-key', 'x-goog-user-project'))):
                self._fail("Vertex 요청별 인증 헤더를 확인하세요.")
            request.extensions["mideagent_timeout_seconds"] = self.options.get("timeout", 60)
            self.calls += 1
        request.headers["accept-encoding"] = "identity"
        # SDK environment organization/project defaults are not user workflow choices.
        for field in ("openai-organization", "openai-project"):
            request.headers.pop(field, None)
        if self.key is None:
            for field in ("authorization", "x-api-key", "x-goog-api-key"):
                request.headers.pop(field, None)
        else:
            for field in ("authorization", "x-api-key", "x-goog-api-key"):
                value = request.headers.get(field)
                if value and value not in (self.key, "Bearer " + self.key):
                    self._fail("요청별 인증정보가 아닌 SDK 인증 헤더를 차단했습니다.")
        try:
            response = self.inner.handle_request(request)
        except httpx.HTTPError as error:
            definite = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            failure = EndpointFailure("모델 서버 연결 실패 · 자동 재시도하지 않습니다." if definite else "모델 서버 통신 결과 불명 · 자동 재시도하지 않습니다.", code="connection_failed" if definite else "outcome_unknown")
            failure.upstream_detail = "Vertex transport failed" if self.vertex else redact(type(error).__name__ + ": " + str(error), (self.key,))
            self.failure = failure
            raise failure from None
        try:
            if response.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                self._fail("압축 응답은 제한된 SDK 전송 경로에서 지원하지 않습니다.", "invalid_response")
            body = bytearray()
            limit = MAX_RESPONSE if response.status_code == 200 else 4096
            for part in response.stream:
                body.extend(part[: max(0, limit + 1 - len(body))])
                if len(body) > limit:
                    if response.status_code == 200:
                        self._fail("모델 서버 응답 크기 초과", "invalid_response", capacity_exceeded=True)
                    del body[limit:]
                    break
            if response.status_code != 200:
                status = response.status_code
                code = "rate_limited" if status == 429 else "upstream_failure" if status >= 500 else "authentication_failed" if status in (401, 403) else "request_rejected"
                failure = EndpointFailure("모델 서버 요청 실패 · 자동 재시도하지 않습니다.", code=code)
                failure.http_status = status
                failure.upstream_detail = "Vertex request failed" if self.vertex else redact(body.decode("utf8", errors="replace"), (self.key,))
                self.failure = failure
                raise failure
            try:
                value = json.loads(body)
                stack, count = [(value, 0)], 0
                while stack:
                    item, depth = stack.pop()
                    count += 1
                    if depth > 20 or count > 10000:
                        raise ValueError()
                    if isinstance(item, str) and self.key and self.key in item:
                        raise ValueError()
                    if isinstance(item, dict):
                        stack.extend((v, depth + 1) for pair in item.items() for v in pair)
                    elif isinstance(item, list):
                        stack.extend((v, depth + 1) for v in item)
            except (ValueError, TypeError, RecursionError, UnicodeError):
                self._fail("모델 응답 구조·인증정보 검증에 실패했습니다.", "invalid_response")
            if self.vertex:
                # Bound and type-check before SDK serializers can warn with raw
                # provider values; only the implemented text response enters SDK.
                try:
                    candidates = value['candidates']
                    if not isinstance(candidates, list) or len(candidates) != 1:
                        raise ValueError()
                    candidate = candidates[0]
                    parts = candidate['content']['parts']
                    if candidate.get('finishReason') != 'STOP' or not isinstance(parts, list) or not 1 <= len(parts) <= 100:
                        raise ValueError()
                    clean_parts = []
                    for part in parts:
                        if not isinstance(part, dict) or not isinstance(part.get('text'), str) or type(part.get('thought', False)) is not bool:
                            raise ValueError()
                        clean_parts.append({'text': part['text'], **({'thought': True} if part.get('thought') else {})})
                    usage = value.get('usageMetadata', {})
                    if not isinstance(usage, dict):
                        raise ValueError()
                    counts = {}
                    for key in ('promptTokenCount', 'candidatesTokenCount', 'totalTokenCount', 'thoughtsTokenCount', 'cachedContentTokenCount'):
                        if key in usage:
                            if type(usage[key]) is not int or usage[key] < 0:
                                raise ValueError()
                            counts[key] = usage[key]
                    value = {'candidates': [{'content': {'role': 'model', 'parts': clean_parts}, 'finishReason': 'STOP', 'index': 0}], 'usageMetadata': counts}
                    body = json.dumps(value, allow_nan=False).encode()
                except (ValueError, TypeError, KeyError):
                    self._fail('Vertex 구조화 응답 형식 오류', 'invalid_response')
            return httpx.Response(response.status_code, headers=response.headers, content=bytes(body), extensions=response.extensions)
        finally:
            response.close()

    def close(self):
        self.inner.close()

    @staticmethod
    def _schema_shape(value):
        if isinstance(value, list):
            return [_GuardedTransport._schema_shape(item) for item in value]
        if isinstance(value, dict):
            return {key: (_GuardedTransport._schema_shape(item).lower() if key == "type" and isinstance(item, str) else _GuardedTransport._schema_shape(item)) for key, item in value.items() if key not in {"propertyOrdering", "additionalProperties", "maxItems", "title", "description"}}
        return value

    def _validate_schema_and_options(self, body):
        config = body.get("generationConfig", body)
        schema = config.get("response_json_schema", config.get("responseJsonSchema", config.get("response_schema", config.get("responseSchema"))))
        if schema is None:
            schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema")
        if schema is None:
            output = body.get("output_config", {}).get("format", body.get("output_format", {}))
            schema = output.get("schema")
        if schema is None and body.get("tool_choice", {}).get("name") == "json_tool_call":
            tools = body.get("tools", [])
            if len(tools) == 1 and tools[0].get("name") == "json_tool_call":
                schema = tools[0].get("input_schema")
        if self._schema_shape(schema) != self._schema_shape(self.schema):
            self._fail("선택 모델의 구조화 응답 스키마를 SDK가 보존하지 못해 요청을 차단했습니다.", "unavailable")
        aliases = {"max_tokens": ("max_tokens", "max_completion_tokens", "max_output_tokens", "maxOutputTokens"), "temperature": ("temperature",), "top_p": ("top_p", "topP"), "seed": ("seed",)}
        for option, keys in aliases.items():
            if option in self.options and not any(config.get(key) == self.options[option] for key in keys):
                self._fail("선택 모델이 요청 옵션을 보존하지 못해 차단했습니다: " + option, "unavailable")
        if "reasoning_effort" in self.options:
            self._validate_reasoning_effort(body)

    def _validate_reasoning_effort(self, body):
        expected = self.options["reasoning_effort"]
        levels = []
        if self.expected.path.endswith(":generateContent"):
            config = body.get("generationConfig", {})
            containers = [config[key] for key in ("thinking_config", "thinkingConfig") if key in config]
            if len(containers) == 1:
                thinking = containers[0]
                allowed = {"thinking_level", "thinkingLevel", "include_thoughts", "includeThoughts"}
                if isinstance(thinking, dict) and not set(thinking) - allowed:
                    levels = [thinking[name] for name in ("thinking_level", "thinkingLevel") if name in thinking]
        elif self.expected.path.endswith("/v1/messages"):
            thinking = body.get("thinking", {})
            output = body.get("output_config", {})
            if isinstance(thinking, dict) and thinking.get("type", "adaptive") in {"adaptive", "enabled"} and isinstance(output, dict):
                budget = thinking.get("budget_tokens", 1)
                if type(budget) in (int, float) and budget > 0:
                    levels = [output.get("effort")]
        else:
            levels = [body.get("reasoning_effort")]
        # Token budgets are not model-independent effort levels. Do not guess a
        # numeric budget/disabled setting is equivalent to the frozen selection.
        if not levels or any(not isinstance(level, str) or level.lower() != expected for level in levels):
            self._fail("선택 모델의 추론 강도를 SDK가 같은 값으로 보존하지 못해 요청을 차단했습니다.", "unavailable")


class LiteLLMAdapter:
    def __init__(self, endpoint, *, protocol, contract, transport, approved_origins, api_key=None):
        self.endpoint = validate_endpoint(endpoint)
        url = urlsplit(self.endpoint)
        if f"{url.scheme}://{url.netloc}" not in approved_origins or transport is None or protocol not in SDK_PROTOCOLS:
            raise ValueError("승인된 공급자 transport와 origin이 필요합니다.")
        if protocol != 'vertex_ai' and api_key is not None and (not isinstance(api_key, str) or not 1 <= len(api_key) <= 4096 or any(ord(c) < 32 for c in api_key)):
            raise ValueError("인증정보 형식 오류")
        if not isinstance(contract, dict) or contract.get("version") != 1 or contract.get("adapter") != "litellm" or contract.get("provider") != SDK_PROTOCOLS[protocol]:
            raise ValueError("고정된 SDK 호출 계약을 확인하세요.")
        if protocol == 'vertex_ai':
            from video_service.vertex_config import parse_service_account, vertex_endpoint
            parse_service_account(api_key)
            if self.endpoint != vertex_endpoint(contract.get('vertex_project'), contract.get('vertex_location')) or 'https://oauth2.googleapis.com' not in approved_origins:
                raise ValueError('승인된 Vertex 프로젝트·위치·OAuth origin이 필요합니다.')
        self._auth_transport, self._approved_origins = transport, approved_origins
        self._invocation_lock, self._invoked = Lock(), False
        self.contract = deepcopy(contract)
        self.options = parse_options(json.dumps(contract["options"], allow_nan=False))
        self.protocol, self._key, self.model = protocol, api_key, contract["model"]
        self.operation = contract["operation"]
        validate_operation_options(self.operation, self.options)
        if self.operation not in {"translation", "structured_audio", "audio_transcription"}:
            raise ValueError("구현되지 않은 SDK 요청 방식입니다.")
        if not isinstance(self.model, str) or not 1 <= len(self.model) <= 200 or any(c in self.model for c in "?#\\") or any(p in (".", "..") for p in self.model.split("/")):
            raise ValueError("선택 모델 ID 형식을 확인하세요.")
        if self.operation == "audio_transcription":
            if protocol not in {"openai", "openai_compatible", "gemini"}:
                raise ValueError("이 공급자의 시간 정보 전사 API는 연결되지 않았습니다.")
            path = "/interactions" if protocol == "gemini" else "/audio/transcriptions"
        else:
            path = "/models/" + self.model + ":generateContent" if protocol in {"gemini", "vertex_ai"} else "/v1/messages" if protocol == "anthropic" else "/chat/completions"
        self._guard = _GuardedTransport(transport, self.endpoint, path, api_key, self.model, self.options)
        self._client = httpx.Client(transport=self._guard, trust_env=False, follow_redirects=False, timeout=self.options.get("timeout", 60))

    def close(self):
        self._client.close()

    def _arguments(self, model):
        if model != self.model:
            raise ValueError("워크플로우에서 고정한 모델과 요청 모델이 다릅니다.")
        sdk = _sdk()
        from litellm.llms.custom_httpx.http_handler import HTTPHandler
        if self.protocol in {"openai", "openai_compatible"}:
            from openai import OpenAI
            client = OpenAI(api_key=self._key or "mideagent-keyless", base_url=self.endpoint, http_client=self._client, max_retries=0, organization="", project="")
        else:
            client = HTTPHandler(client=self._client, follow_redirects=False)
        options = {k: v for k, v in self.options.items() if k not in {"audio_api", "timeout"}}
        args = dict(model=model, custom_llm_provider=self.contract["provider"], api_base=self.endpoint, api_key=self._key or "mideagent-keyless", client=client,
                    max_retries=0, num_retries=0, caching=False, cache={"no-cache": True, "no-store": True}, timeout=self._client.timeout,
                    **{"no-log": True}, **options)
        if self.protocol == 'vertex_ai':
            from .vertex_auth import acquire_token
            # Client ownership stays with this adapter; OAuth's short-lived client
            # must not close the shared pinned transport before inference.
            class Borrowed(httpx.BaseTransport):
                def handle_request(_, request):
                    return self._auth_transport.handle_request(request)
            token = acquire_token(self._key, transport=Borrowed(), approved_origins=self._approved_origins, timeout=self.options.get('timeout', 60))
            self._guard.key = token
            args.update(api_key=token, vertex_project=self.contract['vertex_project'], vertex_location=self.contract['vertex_location'])
        return sdk, args

    def _completion(self, sdk, args, **kwargs):
        if self.protocol == 'vertex_ai':
            from .vertex_driver import completion
            return completion(sdk, args, **kwargs)
        return sdk.completion(**args, **kwargs)

    def _run(self, model, invoke):
        try:
            if self.protocol == 'vertex_ai':
                with self._invocation_lock:
                    if self._invoked:
                        raise EndpointFailure('Vertex 자동 재호출을 차단했습니다.', code='outcome_unknown')
                    self._invoked = True
            sdk, args = self._arguments(model)
            return invoke(sdk, args)
        except EndpointFailure:
            raise
        except Exception:
            if self._guard.failure is not None:
                raise self._guard.failure from None
            code = "outcome_unknown" if self._guard.calls else "unavailable"
            raise EndpointFailure("선택 모델의 SDK 요청·응답 계약을 확인하세요. 자동 재호출하지 않습니다.", code=code) from None

    def _schema(self, name, schema):
        strict = True
        if self.protocol in {"gemini", "vertex_ai"} and self.operation == "structured_audio":
            # The bounded strict nested audio schema was rejected by the live
            # provider. Keep required fields/types on the wire and enforce
            # counts, text, timestamps and the envelope locally as before.
            def portable(value):
                if isinstance(value, dict):
                    return {key: portable(item) for key, item in value.items()
                            if key not in {"additionalProperties", "maxItems"}}
                if isinstance(value, list):
                    return [portable(item) for item in value]
                return value
            schema, strict = portable(schema), False
        return {"type": "json_schema", "json_schema": {"name": name, "strict": strict, "schema": schema}}

    @staticmethod
    def _object_response(response):
        try:
            choice = response.choices[0]
            text = choice.message.content
            if choice.finish_reason != "stop" or not isinstance(text, str):
                raise ValueError()
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise EndpointFailure("완료된 구조화 모델 응답이 아닙니다.") from None

    def chat(self, model, messages):
        if self.operation != "translation" or not isinstance(messages, list) or not 1 <= len(messages) <= 100 or len(json.dumps(messages).encode()) > 131072:
            raise ValueError("번역 모델 요청 형식을 확인하세요.")
        for item in messages:
            if not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in {"system", "user", "assistant"} or not isinstance(item["content"], str) or len(item["content"]) > 16000:
                raise ValueError("번역 모델 메시지 형식을 확인하세요.")
        outgoing = deepcopy(messages)
        outgoing.insert(0, {"role": "system", "content": 'API output envelope: return a JSON object {"translations": [...]} wrapping the requested translated string array. Keep its length and order. No markdown.'})
        schema = {"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "string"}, "maxItems": 100}}, "required": ["translations"], "additionalProperties": False}
        def send(sdk, args):
            self._guard.schema = schema
            args.setdefault("max_tokens", 4096)
            result = self._object_response(self._completion(sdk, args, messages=outgoing, response_format=self._schema("translation", schema), stream=False))
            if set(result) != {"translations"} or not isinstance(result["translations"], list) or any(not isinstance(x, str) for x in result["translations"]):
                raise EndpointFailure("번역 JSON 배열 응답 형식 오류")
            if self.protocol == 'vertex_ai' and (len(result['translations']) > 100 or any(len(x) > 16000 for x in result['translations'])):
                raise EndpointFailure('번역 JSON 배열 응답 크기 초과', code='invalid_response')
            return json.dumps(result["translations"], ensure_ascii=False, allow_nan=False)
        return self._run(model, send)

    def transcribe(self, model, audio, language):
        info = audio_info(audio)
        if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2,3}", language):
            raise ValueError("지원되는 전사 언어를 선택하세요.")
        if self.operation == "structured_audio":
            import base64
            instruction = "Transcribe this audio without translating. Language=" + language + '. Return {"segments":[{"start":number,"end":number,"text":string}]}. Supply actual audio-local second timestamps, never invent missing timing; at most100 nonoverlapping ordered segments. Empty segments only for no speech.'
            messages = [{"role": "user", "content": [{"type": "text", "text": instruction}, {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"}}]}]
            segment = {"type": "object", "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}}, "required": ["start", "end", "text"], "additionalProperties": False}
            schema = {"type": "object", "properties": {"segments": {"type": "array", "items": segment, "maxItems": 100}}, "required": ["segments"], "additionalProperties": False}
            def send(sdk, args):
                self._guard.schema = schema
                args.setdefault("max_tokens", 4096)
                value = self._object_response(self._completion(sdk, args, messages=messages, response_format=self._schema("timed_audio", schema), stream=False))
                if set(value) != {"segments"}:
                    raise EndpointFailure("시간 정보 전사 JSON 형식 오류")
                return value["segments"]
            rows = self._run(model, send)
        elif self.operation == "audio_transcription":
            def send(sdk, args):
                # Transcription is a different supported SDK operation, not a model-name branch.
                for key in ("cache", "num_retries"):
                    args.pop(key, None)
                if self.protocol == "gemini":
                    args["api_base"] = self.endpoint.removesuffix("/v1beta")
                value = sdk.transcription(**args, file=("audio.wav", io.BytesIO(audio), "audio/wav"), response_format="verbose_json", timestamp_granularities=["word"] if self.protocol == "gemini" else ["segment"], **({"language": language} if language != "auto" else {}))
                value = value.model_dump() if hasattr(value, "model_dump") else value
                if not isinstance(value, dict):
                    raise EndpointFailure("시간 정보 전사 응답 형식 오류")
                result = value.get("segments")
                if result is None:
                    words = value.get("words")
                    if not isinstance(words, list) or not words:
                        raise EndpointFailure("실제 전사 시각이 없는 응답입니다.")
                    if len(words) > 1000:
                        raise EndpointFailure("단어별 전사 응답 구간 수 초과")
                    previous_end = 0
                    try:
                        for word in words:
                            timed_segments([{"start": word["start"], "end": word["end"], "text": word["word"]}], info["duration_seconds"])
                            if word["start"] < previous_end:
                                raise ValueError()
                            previous_end = word["end"]
                    except (KeyError, TypeError, ValueError):
                        raise EndpointFailure("전사 단어의 실제 시각이 누락되었거나 겹칩니다.") from None
                    result = []
                    for index in range(0, len(words), 10):
                        group = words[index:index + 10]
                        result.append({"start": group[0]["start"], "end": group[-1]["end"], "text": " ".join(w["word"] for w in group)})
                return result
            rows = self._run(model, send)
        else:
            raise ValueError("이 고정 모델은 전사 요청이 아닙니다.")
        try:
            rows = timed_segments(rows, info["duration_seconds"])
        except (ValueError, TypeError, KeyError):
            raise EndpointFailure("전사 응답의 실제 시각·구간 수·음성 범위가 올바르지 않습니다.", code="invalid_response") from None
        previous = 0
        for row in rows:
            if row["start"] < previous:
                raise EndpointFailure("전사 시각이 겹치거나 순서가 다릅니다.")
            previous = row["end"]
        return rows
