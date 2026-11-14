import json
from pathlib import Path

import pytest


def config(tmp_path, **changes):
    token = tmp_path / 'existing-private-tool-token'
    token.write_text('synthetic-tool-token-' + 'x' * 32)
    value = {'version': 1, 'role': 'translation',
             'tool_url': 'https://private-bridge.invalid:8445/translate',
             'token_file': str(token), 'timeout_seconds': 30, **changes}
    file = tmp_path / 'private-tool-caller.json'
    file.write_text(json.dumps(value))
    return file


def test_lazy_private_caller_sends_only_approved_attempt_identity(tmp_path, monkeypatch):
    from video_service.unit_recovery_transport import PrivateUnitRecoveryClient
    import urllib.request
    calls = []
    class Reply:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, size):
            assert size <= 65537
            return b'{"attempt_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","status":"completed"}'
    class Client:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 30
            assert request.full_url.endswith('/translate/unit-recovery')
            assert json.loads(request.data) == {'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64}
            assert request.get_header('Authorization').startswith('Bearer synthetic-tool-token-')
            return Reply()
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Client())
    caller = PrivateUnitRecoveryClient(config(tmp_path), 'translation')
    assert calls == []
    result = caller('b' * 32, 'c' * 64)
    assert result['status'] == 'completed' and len(calls) == 1


@pytest.mark.parametrize('change', [
    {'tool_url': 'https://user:pass@private-bridge.invalid/translate'},
    {'tool_url': 'https://private-bridge.invalid/translate?redirect=elsewhere'},
    {'tool_url': 'http://private-bridge.invalid/translate'},
    {'tool_url': 'https://private-bridge.invalid/speech'},
    {'timeout_seconds': float('inf')},
    {'timeout_seconds': True},
    {'role': 'vocalization'},
])
def test_invalid_private_config_is_rejected_without_network(tmp_path, change):
    from video_service.unit_recovery_transport import PrivateUnitRecoveryClient
    with pytest.raises(ValueError):
        PrivateUnitRecoveryClient(config(tmp_path, **change), 'translation')('b' * 32, 'c' * 64)


def test_transport_failure_sanitizes_private_body_and_never_retries(tmp_path, monkeypatch):
    from video_service.unit_recovery_transport import PrivateUnitRecoveryClient
    from video_service.postgres import Conflict
    import urllib.request
    calls = []
    class Client:
        def open(self, *_args, **_kwargs):
            calls.append(1)
            raise OSError('synthetic-private-body-and-key-sentinel')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Client())
    with pytest.raises(Conflict) as caught:
        PrivateUnitRecoveryClient(config(tmp_path), 'translation')('b' * 32, 'c' * 64)
    assert 'sentinel' not in str(caught.value)
    assert len(calls) == 1
