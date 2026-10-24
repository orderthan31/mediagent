"""Explicit, administrator-requested official model GETs, never inference calls."""

import http.client
import ipaddress
import json
import socket
import ssl
import time

import httpx

from .model_endpoints import FRONTIER_CONNECTIONS
from .model_profile import supports_transcription, validate_profile
from .postgres import Conflict
from .postgres.registry import resource_id
from .registered_transport import origin_key


class CatalogFailure(ValueError):
    pass


class _OwnedCatalogConnection(http.client.HTTPConnection):
    def close(self):
        # HTTPConnection may close on response headers with Connection: close.
        # The bounded reader owns this socket and must still set its deadline.
        self.sock = None
        super().close()


class CatalogGetTransport(httpx.BaseTransport):
    """Only official catalog GETs; pin DNS once and keep the original TLS/SNI.

    This deliberately does not relax the existing POST-only inference transport
    or activate its runner/policy. No proxy, alternate-address retry or redirect.
    """

    def __init__(self, provider, *, deadline=None):
        if provider not in FRONTIER_CONNECTIONS:
            raise CatalogFailure("model_catalog_origin_denied")
        self.provider = provider
        self.origin = origin_key(FRONTIER_CONNECTIONS[provider][1])
        self.deadline = deadline if deadline is not None else time.monotonic() + 30
        try:
            resolved = tuple(
                dict.fromkeys(
                    row[4][0]
                    for row in socket.getaddrinfo(
                        self.origin[1], 443, type=socket.SOCK_STREAM
                    )
                )
            )
            if not 1 <= len(resolved) <= 32 or any(
                not ipaddress.ip_address(address).is_global
                or ipaddress.ip_address(address).is_multicast
                or ipaddress.ip_address(address).is_reserved
                for address in resolved
            ):
                raise ValueError()
            self.addresses = tuple(
                sorted(resolved, key=lambda value: ipaddress.ip_address(value).version)
            )
            self.context = ssl.create_default_context()
        except (OSError, ValueError):
            raise CatalogFailure(
                "공식 모델 DNS·공용 주소 검증 실패 · 키를 외부로 보내지 않았습니다."
            ) from None

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpx.TransportError("model_catalog_deadline_exceeded")
        return min(5.0, remaining)

    def handle_request(self, request):
        paths = {
            "openai": {"/v1/models"},
            "gemini": {"/v1beta/models"},
            "anthropic": {"/v1/models"},
            "xai": {"/v1/models", "/v1/language-models"},
        }
        allowed_query = {
            "gemini": {"pageSize", "pageToken"},
            "anthropic": {"limit", "after_id"},
        }.get(self.provider, set())
        if (
            request.method != "GET"
            or origin_key(request.url) != self.origin
            or request.url.path not in paths[self.provider]
            or request.url.username
            or request.url.password
            or request.url.fragment
            or request.headers.get("host") != request.url.netloc.decode("ascii")
            or any(
                key not in allowed_query
                or len(value) > 2048
                or any(ord(char) < 32 for char in value)
                for key, value in request.url.params.multi_items()
            )
        ):
            raise httpx.TransportError("model_catalog_request_denied")
        connection = _OwnedCatalogConnection(
            self.origin[1], 443, timeout=self._remaining()
        )
        stream = None
        response = None
        try:
            stream = socket.create_connection(
                (self.addresses[0], 443), timeout=self._remaining()
            )
            stream.settimeout(self._remaining())
            stream = self.context.wrap_socket(stream, server_hostname=self.origin[1])
            stream.settimeout(self._remaining())
            connection.sock = stream
            allowed_headers = {
                "authorization",
                "x-goog-api-key",
                "anthropic-version",
                "accept",
                "user-agent",
            }
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() in allowed_headers
            }
            headers.update(
                {
                    "Host": self.origin[1],
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                }
            )
            connection.request(
                "GET", request.url.raw_path.decode("ascii"), headers=headers
            )
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError()
            content = bytearray()
            while True:
                stream.settimeout(self._remaining())
                part = response.read1(65536)
                if not part:
                    break
                content.extend(part)
                if len(content) > 1048576:
                    raise ValueError()
            return httpx.Response(
                response.status,
                headers=response.getheaders(),
                content=bytes(content),
                request=request,
            )
        except (OSError, ValueError, http.client.HTTPException):
            raise httpx.TransportError("model_catalog_pinned_https_failure") from None
        finally:
            if response is not None:
                response.close()
            connection.close()
            if stream is not None:
                stream.close()


# Capability evidence is not a list of models to show: only IDs returned by the
# selected account's official API enter the picker. Unknown IDs remain unknown.
_OPENAI_TEXT = {
    "gpt-5.5": "gpt-5.5",
    "gpt-5.5-2026-04-23": "gpt-5.5",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-2025-04-14": "gpt-4.1",
}


def classify(provider, item, protocol, *, catalog_items=None):
    model = item["id"]
    profile = None
    evidence = []
    details = None
    if provider == "openai" and model in _OPENAI_TEXT:
        evidence = [
            "https://developers.openai.com/api/docs/models/" + _OPENAI_TEXT[model]
        ]
        profile = {
            "model_types": ["text", "vision"],
            "input_modalities": ["image", "text"],
            "output_modalities": ["text"],
            "capabilities": ["image_understanding", "text_generation"],
        }
    if provider == "openai" and model == "whisper-1":
        evidence = ["https://developers.openai.com/api/docs/models/whisper-1"]
        profile = {
            "model_types": ["speech_recognition"],
            "input_modalities": ["audio"],
            "output_modalities": ["text"],
            "capabilities": ["speech_recognition"],
        }
    if provider == "gemini":
        from .gemini_catalog import classify_gemini

        details = classify_gemini(item, catalog_items)
        if protocol != "gemini":
            details = {
                **details,
                "profile": None,
                "classification_status": "unsupported",
                "profile_variants": {},
                "reason": "Gemini 정본 프로토콜이 아닌 연결에는 용도를 자동 부여하지 않습니다.",
            }
        profile = details["profile"]
        evidence = details["evidence"]
    if (
        provider == "anthropic"
        and model.startswith("claude-")
        and isinstance(item.get("capabilities"), dict)
    ):
        caps = item["capabilities"]
        inputs, kinds, features = ["text"], ["text"], ["text_generation"]
        if (
            isinstance(caps.get("image_input"), dict)
            and caps["image_input"].get("supported") is True
        ):
            inputs.append("image")
            kinds.append("vision")
            features.append("image_understanding")
        if (
            isinstance(caps.get("structured_outputs"), dict)
            and caps["structured_outputs"].get("supported") is True
        ):
            features.append("structured_output")
        profile = {
            "model_types": sorted(kinds),
            "input_modalities": sorted(inputs),
            "output_modalities": ["text"],
            "capabilities": sorted(features),
        }
        evidence = [
            "https://platform.claude.com/docs/en/api/models/list",
            "https://platform.claude.com/docs/en/api/messages/create",
        ]
    if provider == "xai" and isinstance(item.get("_language_metadata"), dict):
        metadata = item["_language_metadata"]
        inputs, outputs = (
            metadata.get("input_modalities"),
            metadata.get("output_modalities"),
        )
        if (
            isinstance(inputs, list)
            and isinstance(outputs, list)
            and "text" in inputs
            and "text" in outputs
        ):
            image = "image" in inputs
            profile = {
                "model_types": ["text", "vision"] if image else ["text"],
                "input_modalities": ["image", "text"] if image else ["text"],
                "output_modalities": ["text"],
                "capabilities": ["image_understanding", "text_generation"]
                if image
                else ["text_generation"],
            }
            evidence = [
                "https://docs.x.ai/developers/rest-api-reference/inference/models"
            ]
    if profile:
        profile = validate_profile(**profile)
    runtime = []
    if profile:
        if "text_generation" in profile["capabilities"] and protocol in (
            "openai",
            "openai_compatible",
            "gemini",
        ):
            runtime.append("translation")
        if supports_transcription(profile, protocol, model):
            runtime.append("transcription")
    result = {
        "id": model,
        "label": model,
        "profile": profile,
        "runtime_uses": sorted(runtime),
        "evidence": evidence,
        "inference_verified": False,
        "reason": "목록 발견·공식 능력 근거와 현재 어댑터의 교집합입니다. 실제 호출·품질은 미검증입니다."
        if runtime
        else "현재 실행 어댑터가 지원하지 않는 등록 메타데이터입니다."
        if profile
        else "목록에는 있지만 확인된 능력 근거가 없어 용도를 자동 부여하지 않습니다.",
    }
    if details:
        result.update(
            {
                key: details[key]
                for key in (
                    "classification_status",
                    "provider_purpose",
                    "reason",
                    "evidence",
                )
            }
        )
    if details and details.get("profile_variants"):
        variants = {}
        for purpose, variant in details["profile_variants"].items():
            declared = validate_profile(**variant["profile"])
            uses = []
            if "text_generation" in declared["capabilities"]:
                uses.append("translation")
            if supports_transcription(declared, protocol, model):
                uses.append("transcription")
            if purpose in uses:
                variants[purpose] = {
                    **variant,
                    "profile": declared,
                    "runtime_uses": sorted(uses),
                }
        if variants:
            result["profile_variants"] = variants
    return result


def _check_json(value, secret):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 20 or nodes > 20000:
            raise CatalogFailure("model_catalog_invalid_response")
        if isinstance(item, str) and secret and secret in item:
            raise CatalogFailure("model_catalog_secret_echo_rejected")
        if isinstance(item, dict):
            pending.extend((x, depth + 1) for pair in item.items() for x in pair)
        elif isinstance(item, list):
            pending.extend((x, depth + 1) for x in item)


def _get(client, url, secret, deadline, *, params=None):
    if time.monotonic() > deadline:
        raise CatalogFailure("model_catalog_deadline_exceeded")
    try:
        with client.stream("GET", url, params=params) as response:
            status = response.status_code
            if status != 200:
                code = {
                    401: "공급자 키 인증 거부 (401)",
                    403: "공급자 모델 조회 권한 거부 (403)",
                    429: "공급자 모델 조회 제한 (429) · 자동 재시도하지 않습니다.",
                }.get(status, "공급자 모델 조회 실패")
                raise CatalogFailure(code)
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > 1048576 or time.monotonic() > deadline:
                    raise CatalogFailure("model_catalog_response_limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CatalogFailure("model_catalog_invalid_response")
        _check_json(value, secret)
        return value
    except httpx.HTTPError:
        raise CatalogFailure(
            "공급자 모델 조회 통신 실패 · 목록을 확인하지 못했습니다."
        ) from None
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        if isinstance(exc, CatalogFailure):
            raise
        raise CatalogFailure("model_catalog_invalid_response") from None


def _rows(value, field, *, optional=False):
    rows = value.get(field, [] if optional else None)
    if not isinstance(rows, list) or len(rows) > 1000:
        raise CatalogFailure("model_catalog_invalid_response")
    return rows


def fetch_catalog(provider, secret, *, transport=None):
    protocol, endpoint = FRONTIER_CONNECTIONS[provider]
    headers = (
        {"x-goog-api-key": secret}
        if provider == "gemini"
        else {"Authorization": "Bearer " + secret}
    )
    if provider == "anthropic":
        headers["anthropic-version"] = "2026-10-21"
    deadline = time.monotonic() + 30
    rows, cursor, cursors = [], None, set()
    if transport is None:
        transport = CatalogGetTransport(provider, deadline=deadline)
    with httpx.Client(
        transport=transport,
        headers=headers,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(5.0),
    ) as client:
        path = "/v1/models" if provider == "anthropic" else "/models"
        for _ in range(10):
            params = (
                {"pageSize": 100, **({"pageToken": cursor} if cursor else {})}
                if provider == "gemini"
                else {"limit": 100, **({"after_id": cursor} if cursor else {})}
                if provider == "anthropic"
                else None
            )
            value = _get(client, endpoint + path, secret, deadline, params=params)
            page = _rows(
                value,
                "models" if provider == "gemini" else "data",
                optional=provider == "gemini",
            )
            for row in page:
                if not isinstance(row, dict):
                    raise CatalogFailure("model_catalog_invalid_response")
                if provider == "gemini":
                    name = row.get("name")
                    methods = row.get("supportedGenerationMethods", [])
                    if (
                        not isinstance(methods, list)
                        or len(methods) > 100
                        or any(
                            not isinstance(method, str) or len(method) > 200
                            for method in methods
                        )
                    ):
                        raise CatalogFailure("model_catalog_invalid_generation_methods")
                    if not isinstance(name, str) or not name.startswith("models/"):
                        raise CatalogFailure("model_catalog_invalid_model_id")
                    row = {**row, "id": name[7:]}
                rows.append(row)
            if len(rows) > 1000:
                raise CatalogFailure("model_catalog_model_limit")
            if provider == "gemini":
                next_cursor = value.get("nextPageToken")
                if next_cursor is not None and not isinstance(next_cursor, str):
                    raise CatalogFailure("model_catalog_invalid_pagination")
            elif provider == "anthropic":
                if type(value.get("has_more")) is not bool:
                    raise CatalogFailure("model_catalog_invalid_pagination")
                next_cursor = value.get("last_id") if value["has_more"] else None
                if value["has_more"] and not next_cursor:
                    raise CatalogFailure("model_catalog_invalid_pagination")
            else:
                if value.get("has_more") or value.get("nextPageToken"):
                    raise CatalogFailure("model_catalog_unsupported_pagination")
                next_cursor = None
            if not next_cursor:
                break
            if (
                not isinstance(next_cursor, str)
                or len(next_cursor) > 2048
                or next_cursor in cursors
            ):
                raise CatalogFailure("model_catalog_invalid_pagination")
            cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise CatalogFailure("model_catalog_page_limit")
        if provider == "xai":
            metadata = _rows(
                _get(client, endpoint + "/language-models", secret, deadline), "models"
            )
            by_id = {}
            for item in metadata:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    raise CatalogFailure("model_catalog_invalid_response")
                aliases = item.get("aliases", [])
                if (
                    not isinstance(aliases, list)
                    or len(aliases) > 100
                    or any(
                        not isinstance(alias, str) or len(alias) > 200
                        for alias in aliases
                    )
                ):
                    raise CatalogFailure("model_catalog_invalid_response")
                for name in [item["id"], *aliases]:
                    if name in by_id and by_id[name] != item:
                        raise CatalogFailure("model_catalog_ambiguous_model")
                    by_id[name] = item
            rows = [
                {**row, "_language_metadata": by_id.get(row.get("id"))} for row in rows
            ]
    result, seen = [], set()
    for row in rows:
        if (
            not isinstance(row.get("id"), str)
            or not 1 <= len(row["id"]) <= 200
            or any(ord(c) < 32 for c in row["id"])
        ):
            raise CatalogFailure("model_catalog_invalid_model_id")
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        result.append(
            classify(
                provider,
                row,
                protocol,
                catalog_items=rows if provider == "gemini" else None,
            )
        )
    return result


class ModelCatalog:
    def __init__(self, registry, credentials, *, transport=None):
        self.registry = registry
        self.credentials = credentials
        self.transport = transport

    def query(self, owner, connection_id, revision):
        resource_id(owner)
        resource_id(connection_id)
        with self.registry.database.connection() as db:
            parent, row = self.registry._connection(db, owner, connection_id)
        if not parent["active"] or row["revision"] != revision:
            raise Conflict("공급자 연결이 변경됐습니다. 최신 연결을 다시 선택하세요.")
        if row["provider"] not in FRONTIER_CONNECTIONS:
            raise CatalogFailure(
                "Custom 연결은 수동 모델 등록을 유지합니다. 임의 주소로 키를 전송하지 않습니다."
            )
        if (row["protocol"], row["endpoint"]) != FRONTIER_CONNECTIONS[row["provider"]]:
            raise CatalogFailure(
                "기존 별도 주소를 보존했습니다. 공식 조회에는 새 공식 공급자 연결을 등록하세요."
            )
        if not row["credential_ref"]:
            raise CatalogFailure("공급자 연결에 저장된 API 키가 없습니다.")
        secret = self.credentials.resolve(owner, connection_id, row["credential_ref"])
        models = fetch_catalog(row["provider"], secret, transport=self.transport)
        del secret
        with self.registry.database.connection() as db:
            latest, current = self.registry._connection(db, owner, connection_id)
        if (
            not latest["active"]
            or current["sha256"] != row["sha256"]
            or current["revision"] != revision
        ):
            raise Conflict(
                "조회 중 공급자 연결이 변경됐습니다. 목록을 다시 조회하세요."
            )
        for model in models:
            selections = [model, *model.get("profile_variants", {}).values()]
            for selection in selections:
                if selection["profile"]:
                    selection["registration_token"] = (
                        self.credentials.seal_catalog_entry(
                            owner,
                            connection_id,
                            {
                                "connection_revision": revision,
                                "connection_sha256": row["sha256"],
                                "model": model["id"],
                                "profile": selection["profile"],
                            },
                        )
                    )
        return {
            "provider": row["provider"],
            "connection_id": connection_id,
            "connection_revision": revision,
            "complete": True,
            "models": models,
            "inference_verified": False,
            "notice": "공식 모델 목록 조회입니다. 생성·전사·번역은 실행하지 않았습니다.",
        }
