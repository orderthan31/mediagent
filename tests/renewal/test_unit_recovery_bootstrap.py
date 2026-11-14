"""Composition to private recovery transport is opt-in and lazy, never provider I/O."""
from pathlib import Path
from types import SimpleNamespace
import json
import socket

import pytest


def forbidden(*_args, **_kwargs):
    pytest.fail('composition/preview must not open a socket or resolve a key')


def test_private_recovery_factory_is_lazy_and_role_bound(monkeypatch):
    from mideagent_orchestrator.bootstrap import runtime_components
    from video_service import transport_files, registered_transport
    from video_service.postgres.credentials import CredentialStore
    from video_service.postgres.unit_recovery import RoleUnitRecovery
    from video_service.unit_recovery_transport import PrivateUnitRecoveryClient
    from video_service.postgres import Conflict

    for name in ('create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    store, factory = SimpleNamespace(storage_kind='s3'), SimpleNamespace()
    vault = SimpleNamespace(resolve=forbidden)
    policy = SimpleNamespace(mode='external', approved_origins=frozenset({'https://example.invalid'}),
                             transport=forbidden, sha256='f'*64)
    monkeypatch.setattr(registered_transport.RegisteredPolicy, 'from_file', lambda *a, **k: policy)
    monkeypatch.setattr(transport_files, 'object_store', lambda *a: store)
    monkeypatch.setattr(transport_files, 'broker_factory', lambda *a: factory)
    monkeypatch.setattr(transport_files, 'registered_broker_factory', lambda *a: object())
    monkeypatch.setattr(CredentialStore, 'from_file', lambda *a: vault)
    config = {key: 'synthetic-private-fixture' for key in (
        'object_config_file','broker_config_file','credential_key_file',
        'registered_model_config_file','registered_broker_config_file')}
    config.update(admission_policy={'mode':'normal'},
        unit_recovery_translation_tool_config_file='/private/current-mt-tool.json')
    calls = []
    class Caller:
        def __init__(self, path, role):
            calls.append(('config', path, role))
        def __call__(self, attempt, context):
            calls.append(('send', attempt, context))
            return {'attempt_id':attempt,'status':'completed'}
    monkeypatch.setattr('video_service.unit_recovery_transport.PrivateUnitRecoveryClient', Caller)
    monkeypatch.setattr(RoleUnitRecovery, 'load_retry_attempt', lambda *_: {'role':'translation'})
    got = runtime_components(object(), config, enable_broker=True, enable_registered=True)
    assert got == (store,vault,factory) and calls == []
    assert factory.unit_recovery_roles == {'translation'}
    assert factory.unit_recovery_executor('a'*32,'b'*64)['status'] == 'completed'
    assert calls == [('config','/private/current-mt-tool.json','translation'),('send','a'*32,'b'*64)]
    monkeypatch.setattr(RoleUnitRecovery, 'load_retry_attempt', lambda *_: {'role':'vocalization'})
    with pytest.raises(Conflict, match='transport_unavailable'):
        factory.unit_recovery_executor('a'*32,'b'*64)
    assert len(calls) == 2


def test_private_recovery_files_need_registered_runtime(tmp_path):
    from mideagent_orchestrator.bootstrap import runtime_components
    with pytest.raises(ValueError, match='unit_recovery_requires_registered'):
        runtime_components(object(), {'content_root':str(tmp_path),
            'unit_recovery_transcription_tool_config_file':'/private/speech.json'})


def test_strict_bootstrap_accepts_explicit_absolute_recovery_file_paths(tmp_path):
    from video_service.bootstrap import load_bootstrap
    dsn = tmp_path/'synthetic-dsn'; dsn.write_text('postgresql://synthetic.invalid/unused')
    config = dict(database_dsn_file=str(dsn),content_root=str(tmp_path/'content'),
        allowed_origins=['https://test.invalid'],host='127.0.0.1',port=8000,secure_cookies=True,
        unit_recovery_transcription_tool_config_file=str(tmp_path/'speech.json'),
        unit_recovery_translation_tool_config_file=str(tmp_path/'mt.json'))
    path=tmp_path/'bootstrap.json';path.write_text(json.dumps(config))
    assert load_bootstrap(path)[0] == config
    config['unit_recovery_translation_tool_config_file']='relative.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='invalid_bootstrap_file'):
        load_bootstrap(path)
