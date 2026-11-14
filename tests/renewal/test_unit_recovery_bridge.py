"""Private recovery bridge: fresh approved identities, no old tool-slot recalls."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from video_service.canonical import digest
from video_service.role_policy import model_binding


class Decisions:
    def __init__(self, grant):
        self.grant = grant
        self.begins = 0
        self.finished = []
        self.state = 'pending'

    def load_retry_attempt(self, attempt_id, context_sha256):
        assert attempt_id == 'b' * 32 and context_sha256 == 'c' * 64
        return {**deepcopy(self.grant), 'status': self.state}

    def begin_attempt(self, attempt_id, context_sha256):
        self.begins += 1
        if self.state != 'pending':
            return {'newly_sending': False, 'status': self.state}
        self.state = 'sending'
        return {'newly_sending': True, 'status': self.state}

    def finish_attempt(self, attempt_id, status, response=None, error_code=None):
        self.state = status
        self.finished.append((status, response, error_code))
        return {'status': status}


def translation_grant():
    source = [{'id': 'x', 'start': 0.1, 'end': 0.4, 'text': 'original'}]
    pin = {'owner_id': 'owner', 'model_id': 'model', 'revision': 1,
           'connection_id': 'connection', 'credential_ref': 'db:synthetic',
           'remote_model': 'fixed-original-model'}
    task = {'version': 2, 'role_policy_version': 2, 'task_id': 'a' * 32,
            'role': 'translation', 'models': [model_binding(pin)],
            'source_language': 'en', 'target_language': 'ko'}
    return dict(owner_id='owner', job_id='job', run_id='run',
                role='translation', task=task, source=source,
                unit_index=0, candidate_index=0, input_sha256=digest(source),
                pin=pin, approved_calls=1, approve_calls=True)


@contextmanager
def fence(*_args):
    yield


def runtime(monkeypatch, adapter):
    monkeypatch.setattr('video_service.postgres.model_call_fence.model_call_fence', fence)
    key = 'synthetic-private-key'
    executor = SimpleNamespace(available=lambda _pin: True,
        credentials=SimpleNamespace(resolve=lambda *_args: key),
        make_adapter=lambda _pin, got: adapter if got == key else pytest.fail('wrong key'))
    return SimpleNamespace(database=object(), translation_runtime=executor,
                           transcription_runtime=executor)


def test_new_attempt_is_sent_once_and_preserves_original_source(monkeypatch):
    from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
    calls = []
    class Adapter:
        def chat(self, model, messages):
            calls.append(model)
            return '["번역"]'
        def close(self):
            pass
    grant = translation_grant()
    before = deepcopy(grant)
    decisions = Decisions(grant)
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, Adapter()), 'translation', service=decisions)
    packet = {'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64}
    assert bridge.invoke(packet)['status'] == 'completed'
    assert bridge.invoke(packet)['status'] == 'completed'
    assert calls == ['fixed-original-model']
    assert len(decisions.finished) == 1
    assert grant == before


def test_wrong_role_and_changed_pin_cannot_consume_approval(monkeypatch):
    from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
    from video_service.postgres import Conflict
    grant = translation_grant()
    decisions = Decisions(grant)
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, object()), 'transcription', service=decisions)
    with pytest.raises(Conflict):
        bridge.invoke({'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64})
    assert decisions.begins == 0
    grant['pin']['revision'] = 2
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, object()), 'translation', service=decisions)
    with pytest.raises(Conflict):
        bridge.invoke({'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64})
    assert decisions.begins == 0


def test_sending_unknown_never_reenters_adapter(monkeypatch):
    from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
    decisions = Decisions(translation_grant())
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, object()), 'translation', service=decisions)
    for state in ['sending', 'unknown']:
        decisions.state = state
        assert bridge.invoke({'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64})['status'] == state
    assert decisions.finished == []


def test_exception_after_adapter_entry_is_unknown_and_not_retried(monkeypatch):
    from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
    calls = []
    class Adapter:
        def chat(self, *_args):
            calls.append(True)
            raise OSError('synthetic-private-sentinel must not escape')
        def close(self):
            pass
    decisions = Decisions(translation_grant())
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, Adapter()), 'translation', service=decisions)
    packet = {'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64}
    first = bridge.invoke(packet)
    assert first['status'] == 'unknown'
    assert 'sentinel' not in str(first)
    assert bridge.invoke(packet)['status'] == 'unknown'
    assert len(calls) == 1


def test_bad_translation_response_is_a_known_failed_new_attempt(monkeypatch):
    from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
    class Adapter:
        def chat(self, *_args):
            return [{'start': 1, 'end': 2, 'text': 'changed identity'}]
        def close(self):
            pass
    decisions = Decisions(translation_grant())
    bridge = UnitRecoveryToolBridge(runtime(monkeypatch, Adapter()), 'translation', service=decisions)
    response = bridge.invoke({'attempt_id': 'b' * 32, 'context_sha256': 'c' * 64})
    assert response['status'] == 'failed'
    assert decisions.finished[0][2] == 'invalid_response'
