"""Offline token boundary; no credential files or cloud calls."""
import sys
from pathlib import Path
import httpx
import pytest
ROOT = Path(__file__).resolve().parents[2]
for p in ('packages/shared', 'tools/models'):
    sys.path.insert(0, str(ROOT / p))


def test_fixed_single_oauth_send():
    from mideagent_model_tools.vertex_auth import GoogleOAuthRequest, TOKEN_URI
    seen = []
    def send(request):
        seen.append(request)
        return httpx.Response(200, json={'access_token': 'fake-token', 'expires_in': 3600, 'token_type': 'Bearer'})
    with GoogleOAuthRequest(httpx.MockTransport(send), 5) as request:
        assert request(TOKEN_URI, method='POST', body=b'assertion=fake').status == 200
        with pytest.raises(ValueError):
            request(TOKEN_URI, method='POST', body=b'assertion=fake')
    assert len(seen) == 1


@pytest.mark.parametrize('url,method', [('http://metadata.google.internal/token','GET'), ('https://evil.invalid/token','POST'), ('https://oauth2.googleapis.com/token','GET')])
def test_oauth_rejects_before_wire(url, method):
    from mideagent_model_tools.vertex_auth import GoogleOAuthRequest
    with GoogleOAuthRequest(httpx.MockTransport(lambda r: pytest.fail('wire')), 5) as request:
        with pytest.raises(ValueError):
            request(url, method=method)


@pytest.mark.parametrize('status', [302, 401, 429, 500])
def test_auth_error_sanitized(status):
    from mideagent_model_tools.vertex_auth import GoogleOAuthRequest, TOKEN_URI
    seen = []
    def send(r):
        seen.append(r)
        return httpx.Response(status, content=b'private-sentinel', headers={'location': 'https://evil.invalid'})
    with GoogleOAuthRequest(httpx.MockTransport(send), 5) as request:
        with pytest.raises(ValueError, match='Google OAuth request failed') as caught:
            request(TOKEN_URI, method='POST', body=b'assertion=fake')
        assert 'private-sentinel' not in str(caught.value)
    assert len(seen) == 1
