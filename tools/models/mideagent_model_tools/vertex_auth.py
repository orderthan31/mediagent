"""Request-owned service-account OAuth, exclusively over injected pinned egress."""
import importlib.metadata
import json
import time
from threading import Lock
from types import SimpleNamespace
import httpx

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GoogleOAuthRequest:
    def __init__(self, transport, timeout):
        if transport is None or not 1 <= timeout <= 120:
            raise ValueError("Google OAuth transport required")
        self.deadline = time.monotonic() + timeout
        self.calls = 0
        self.lock = Lock()
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        try:
            with self.lock:
                if url != TOKEN_URI or method != "POST" or self.calls or time.monotonic() >= self.deadline:
                    raise ValueError()
                if not isinstance(body, (str, bytes)) or len(body) > 65536:
                    raise ValueError()
                self.calls += 1
            remaining = self.deadline - time.monotonic()
            # Never forward arbitrary google-auth headers or a caller token URI.
            with self.client.stream("POST", TOKEN_URI, content=body,
                    headers={"content-type": "application/x-www-form-urlencoded", "accept-encoding": "identity"},
                    timeout=min(remaining, 15)) as response:
                if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > 16384 or time.monotonic() >= self.deadline:
                        raise ValueError()
                    raw.extend(chunk)
                data = json.loads(raw)
                token = data.get("access_token")
                if (not isinstance(token, str) or not 1 <= len(token) <= 8192
                        or any(ord(c) < 33 or ord(c) > 126 for c in token)
                        or data.get("token_type", "Bearer") != "Bearer"
                        or type(data.get("expires_in")) is not int or not 1 <= data["expires_in"] <= 86400):
                    raise ValueError()
                safe = {"access_token": token, "token_type": "Bearer", "expires_in": data["expires_in"]}
                return SimpleNamespace(status=200, data=json.dumps(safe).encode(), headers={})
        except Exception:
            raise ValueError("Google OAuth request failed") from None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()


def acquire_token(secret, *, transport, approved_origins, timeout=60):
    from .endpoints import EndpointFailure
    try:
        if "https://oauth2.googleapis.com" not in approved_origins:
            raise ValueError()
        from video_service.vertex_config import parse_service_account
        info = parse_service_account(secret)
        if importlib.metadata.version("google-auth") != "2.62.2":
            raise ValueError()
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        with GoogleOAuthRequest(transport, timeout) as request:
            credentials.refresh(request)
        token = credentials.token
        if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError()
        return token
    except Exception:
        raise EndpointFailure("Vertex 인증 실패 · 자동 재시도하지 않습니다.", code="authentication_failed") from None
