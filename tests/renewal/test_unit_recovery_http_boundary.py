"""Existing private endpoint authenticates/selects the recovery operation only."""
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from mideagent_model_tools.bridge import ToolServer


def post(server, path, token, body):
    conn = http.client.HTTPConnection(*server.server_address, timeout=3)
    conn.request('POST', path, body=json.dumps(body),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    response = conn.getresponse()
    result = response.status, response.read()
    conn.close()
    return result


def make_server(role):
    def unexpected(*_args):
        pytest.fail('unit recovery must not enter an old model/tool slot')
    bridge = SimpleNamespace(slots=threading.BoundedSemaphore(1),
        roles=SimpleNamespace(runtime=object()), invoke=unexpected,
        invoke_translation=unexpected, invoke_vocalization=unexpected)
    token = 'synthetic-private-tool-token-' + 'x' * 32
    server = ToolServer(('127.0.0.1', 0), bridge, token, role=role)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    return server, thread, token


def test_recovery_route_uses_new_namespace_with_existing_auth(monkeypatch):
    calls = []
    class Recovery:
        def __init__(self, _runtime, role):
            assert role == 'translation'
        def invoke(self, packet):
            calls.append(packet)
            return {'attempt_id': packet['attempt_id'], 'status': 'completed'}
    monkeypatch.setattr('mideagent_model_tools.unit_recovery.UnitRecoveryToolBridge', Recovery)
    server, thread, token = make_server('translation')
    packet = {'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64}
    try:
        assert post(server, '/translate/unit-recovery', 'wrong-token', packet)[0] == 403
        assert calls == []
        status, raw = post(server, '/translate/unit-recovery', token, packet)
        assert status == 200 and json.loads(raw)['status'] == 'completed'
        assert calls == [packet]
        status, raw = post(server, '/translate/unit-recovery', token,
                           {'attempt_id': 'synthetic-private-sentinel', 'context_sha256': 'c' * 64})
        assert status == 409 and b'sentinel' not in raw
        assert calls == [packet]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_vocalization_does_not_advertise_unimplemented_recovery(monkeypatch):
    server, thread, token = make_server('vocalization')
    try:
        assert post(server, '/vocal/unit-recovery', token,
            {'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64})[0] == 403
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
