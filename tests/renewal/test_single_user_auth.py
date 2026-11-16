"""Offline auth-boundary tests; no database, edge, credentials or providers."""
from contextlib import contextmanager
import socket

import pytest
from fastapi.testclient import TestClient

from app.admission import AdmissionPolicy
from app.renewal import create_app
from app.single_user import from_environment
from video_service.postgres.accounts import Accounts, csrf_for, digest
from video_service.postgres.registry import Registry

ORIGIN = "https://private.example.test"
ACCOUNT = "a" * 32
TOKEN = "s" * 43


class ReadOnlyDatabase:
    def __init__(self):
        self.row = dict(id=ACCOUNT, username="existing-owner", role="admin", active=True,
                        created_at="2026-01-01T00:00:00Z")
        self.queries = []
        self.result = None

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        assert sql.startswith("SELECT "), "auth must never write database state"
        if sql == "SELECT 1 FROM accounts LIMIT 1":
            self.result = {"exists": 1} if self.row else None
        elif sql.startswith("SELECT id,username,role,active,created_at FROM accounts"):
            self.result = (dict(self.row) if self.row and self.row['active']
                           and params == (self.row['id'],) else None)
        elif sql.startswith("SELECT a.*,s.csrf_hash FROM sessions"):
            assert params == (digest(TOKEN),)
            self.result = {**self.row, "csrf_hash": digest(csrf_for(TOKEN))}
        else:
            raise AssertionError("unexpected database operation: " + sql)
        return self

    def fetchone(self):
        return self.result


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unexpected network/provider call")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def app_for(db, **overrides):
    args = dict(allowed_origins=(ORIGIN,), single_user_account=ACCOUNT,
                single_user_private_origin=ORIGIN)
    args.update(overrides)
    return create_app(db, **args)


def test_default_401_and_existing_session_survives_restore():
    db = ReadOnlyDatabase()
    normal = dict(single_user_account=None, single_user_private_origin=None)
    with TestClient(app_for(db, **normal), base_url=ORIGIN) as client:
        assert client.get('/api/capabilities').status_code == 401
        assert client.get('/api/auth/session').json()['enabled'] is True
        client.cookies.set('__Host-mideagent_session', TOKEN)
        assert client.get('/api/auth/session').json()['user']['id'] == ACCOUNT
    with TestClient(app_for(db), base_url=ORIGIN) as client:
        result = client.get('/api/auth/session')
        assert result.status_code == 200
        assert result.json()['enabled'] is False
        assert result.json()['user'] == db.row
        assert result.json()['setup_required'] is False
        assert result.headers['cache-control'] == 'no-store'
        assert 'set-cookie' not in result.headers
        capabilities = client.get('/api/capabilities').json()
        assert capabilities['execution_enabled'] is False
        assert capabilities['model_network_enabled'] is False
    with TestClient(app_for(db, **normal), base_url=ORIGIN) as client:
        assert client.get('/api/capabilities').status_code == 401
        client.cookies.set('__Host-mideagent_session', TOKEN)
        assert client.get('/api/capabilities').status_code == 200


def test_csrf_origin_role_and_bound_owner(monkeypatch):
    db = ReadOnlyDatabase()
    writes = []
    def save(self, owner, identity, **body):
        writes.append((owner, identity, body))
        return {'owner': owner, 'id': identity}
    monkeypatch.setattr(Registry, 'save_connection', save)
    path = '/api/settings/serving-connections/' + 'b' * 32
    body = dict(revision=0, name='fake', provider='openai')
    with TestClient(app_for(db), base_url=ORIGIN) as client:
        token = client.get('/api/auth/session').json()['csrf_token']
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': token}
        for bad in ({}, {'Origin': ORIGIN}, {'X-CSRF-Token': token},
                    {**headers, 'Origin': 'https://evil.example'},
                    {**headers, 'X-CSRF-Token': 'wrong'},
                    {**headers, 'Origin': 'null'}):
            assert client.put(path, json=body, headers=bad).status_code == 403
        assert writes == []
        assert client.get('/api/capabilities', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/capabilities', headers={'Host': 'evil.example'}).status_code == 400
        assert client.put(path, json={**body, 'owner_id': 'c'*32}, headers=headers).status_code == 422
        assert client.put(path, json=body, headers={**headers, 'X-User-Id': 'c'*32}).json()['owner'] == ACCOUNT
        assert writes[0][0] == ACCOUNT
        db.row['role'] = 'user'
        assert client.get('/api/auth/session').json()['user']['role'] == 'user'
        assert client.put(path, json=body, headers=headers).status_code == 403
        assert client.get('/api/accounts').status_code == 403
        assert len(writes) == 1


@pytest.mark.parametrize('row_change', ['deleted', 'inactive', 'invalid_role'])
def test_recheck_revocation_and_startup_fail_closed(row_change):
    db = ReadOnlyDatabase()
    app = app_for(db)
    if row_change == 'deleted':
        db.row = None
    elif row_change == 'inactive':
        db.row['active'] = False
    else:
        db.row['role'] = 'superadmin'
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get('/api/auth/session').status_code == 503
        assert client.get('/api/capabilities').status_code == 503
    with pytest.raises(ValueError, match='active_account_required'):
        app_for(db)


@pytest.mark.parametrize('override', [
    {'single_user_account': ''}, {'single_user_account': ' ' + ACCOUNT},
    {'single_user_account': ACCOUNT.upper()}, {'single_user_account': 'unknown'},
    {'single_user_account': None}, {'single_user_private_origin': None},
    {'single_user_private_origin': 'http://private.example.test'},
    {'single_user_private_origin': ORIGIN + '/'}, {'secure_cookies': False},
    {'allowed_origins': (ORIGIN, 'https://other.example')},
    {'admission_policy': AdmissionPolicy(mode='maintenance', agent_id='analyze', slot_id='d'*32)},
])
def test_invalid_configuration_never_reads_database(override):
    db = ReadOnlyDatabase()
    with pytest.raises(ValueError):
        app_for(db, **override)
    assert db.queries == []


def test_auth_endpoints_disabled_without_changing_sessions(monkeypatch):
    db = ReadOnlyDatabase()
    def forbidden(*args, **kwargs):
        raise AssertionError('account/session mutation is forbidden')
    for method in ('create', 'login', 'logout', 'throttle'):
        monkeypatch.setattr(Accounts, method, forbidden)
    with TestClient(app_for(db), base_url=ORIGIN) as client:
        token = client.get('/api/auth/session').json()['csrf_token']
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': token}
        for route in ('bootstrap', 'login'):
            assert client.post('/api/auth/' + route, headers=headers,
                               json={'username': 'existing', 'password': 'fake-password-123'}).status_code == 409
        assert client.post('/api/auth/logout', headers=headers).status_code == 409
        assert client.get('/api/capabilities').status_code == 200
    with TestClient(app_for(db), base_url=ORIGIN) as client:
        assert client.get('/api/auth/session').json()['csrf_token'] != token


def test_unknown_well_formed_account_is_not_bootstrapped():
    with pytest.raises(ValueError, match='active_account_required'):
        app_for(ReadOnlyDatabase(), single_user_account='e' * 32)


def test_composition_root_wires_opt_in_and_restore_without_network(monkeypatch):
    from app import server
    import mideagent_orchestrator.bootstrap as runtime
    import video_service.postgres as postgres
    import uvicorn

    db = ReadOnlyDatabase()
    config = dict(allowed_origins=[ORIGIN], secure_cookies=True,
                  admission_policy={'mode': 'normal'}, host='127.0.0.1', port=8999)
    monkeypatch.setattr(server, 'load_bootstrap', lambda _: (config, 'fake-unused-dsn'))
    monkeypatch.setattr(postgres, 'Database', lambda _: db)
    monkeypatch.setattr(runtime, 'runtime_components', lambda *a, **k: (None, None, None))
    monkeypatch.setattr('sys.argv', ['server', '--bootstrap-file', '/fake/not-read',
                                    '--admission-mode', 'normal'])
    states = []
    def inspect_app(app, **kwargs):
        assert kwargs['host'] == '127.0.0.1'
        assert kwargs['proxy_headers'] is False
        with TestClient(app, base_url=ORIGIN) as client:
            states.append(client.get('/api/auth/session').json())
    monkeypatch.setattr(uvicorn, 'run', inspect_app)
    monkeypatch.setenv('MIDEAGENT_SINGLE_USER_ACCOUNT', ACCOUNT)
    monkeypatch.setenv('MIDEAGENT_SINGLE_USER_PRIVATE_ORIGIN', ORIGIN)
    server.main()
    monkeypatch.delenv('MIDEAGENT_SINGLE_USER_ACCOUNT')
    monkeypatch.delenv('MIDEAGENT_SINGLE_USER_PRIVATE_ORIGIN')
    server.main()
    assert states[0]['enabled'] is False and states[0]['user']['id'] == ACCOUNT
    assert states[1]['enabled'] is True and states[1]['user'] is None


def test_environment_is_explicit_and_reversible():
    assert from_environment({}) == (None, None)
    env = {'MIDEAGENT_SINGLE_USER_ACCOUNT': ACCOUNT,
           'MIDEAGENT_SINGLE_USER_PRIVATE_ORIGIN': ORIGIN}
    assert from_environment(env) == (ACCOUNT, ORIGIN)
    for bad in ({'MIDEAGENT_SINGLE_USER_ACCOUNT': ACCOUNT},
                {'MIDEAGENT_SINGLE_USER_PRIVATE_ORIGIN': ORIGIN},
                {**env, 'MIDEAGENT_SINGLE_USER_ACCOUNT': ''}):
        with pytest.raises(ValueError):
            from_environment(bad)
