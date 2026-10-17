"""Run only against an explicitly supplied disposable PostgreSQL database.

Each test owns a random schema and removes only that exact schema. Never infer
production DSNs from application configuration or connect to a default database.
"""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import secrets

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from fastapi.testclient import TestClient

from app.renewal import create_app
from video_service.postgres import Database, Conflict, Missing
from video_service.postgres.accounts import Accounts, digest
from video_service.postgres.registry import Registry
from video_service.model_endpoints import OpenAITextAdapter, EndpointFailure, validate_endpoint


@pytest.fixture
def db():
    dsn = os.environ.get('MIDEAGENT_TEST_DSN')
    if not dsn:
        pytest.skip('MIDEAGENT_TEST_DSN must explicitly target a disposable PostgreSQL instance')
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    schema = 'renewal_test_' + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    instance = Database(make_conninfo(dsn, options='-c search_path=' + schema))
    instance.migrate()
    try:
        yield instance
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture
def admin(db):
    password = secrets.token_urlsafe(24)
    user = Accounts(db).create('test-admin', password, first=True)
    return user, password


def app_client(db, *, secure=False):
    return TestClient(create_app(db, allowed_origins=('https://testserver' if secure else 'http://testserver',),
                                 secure_cookies=secure), base_url='https://testserver' if secure else 'http://testserver')


def login(client, admin):
    response = client.post('/api/auth/login', json={'username': admin[0]['username'], 'password': admin[1]})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response


def test_migration_repeat_checksum_and_atomic_rollback(db):
    assert db.migrate() == []
    with db.connection() as conn:
        old = conn.execute("SELECT sha256 FROM schema_migrations WHERE name='001_foundation.sql'").fetchone()['sha256']
        conn.execute("UPDATE schema_migrations SET sha256=%s WHERE name='001_foundation.sql'", ('0' * 64,))
    with pytest.raises(Conflict):
        db.migrate()
    with db.connection() as conn:
        conn.execute("UPDATE schema_migrations SET sha256=%s WHERE name='001_foundation.sql'", (old,))
    with pytest.raises(RuntimeError):
        with db.connection() as conn:
            conn.execute("INSERT INTO login_limits VALUES ('rollback',1,now())")
            raise RuntimeError('synthetic rollback')
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM login_limits WHERE bucket='rollback'").fetchone()['n'] == 0


def test_concurrent_bootstrap_one_admin_and_no_plaintext(db):
    accounts = Accounts(db)
    secret = secrets.token_urlsafe(24)
    def create(index):
        try:
            return accounts.create('admin-' + str(index), secret, first=True)
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(create, [1, 2]))
    assert sum(v is not None for v in result) == 1
    assert not accounts.setup_required()
    with db.connection() as conn:
        row = conn.execute('SELECT * FROM accounts').fetchone()
        assert row['password_hash'].startswith('scrypt-v1$') and secret not in row['password_hash']
        assert row['role'] == 'admin'


def test_auth_csrf_admin_boundaries_revocation_and_secret_errors(db, admin):
    with app_client(db, secure=True) as client:
        assert client.get('/api/auth/session').json()['setup_required'] is False
        assert client.get('/api/accounts').status_code == 401
        assert client.post('/api/auth/bootstrap', json={'username': 'other', 'password': admin[1]}).status_code == 409
        assert client.post('/api/auth/login', json={'username': 'test-admin', 'password': secrets.token_urlsafe(24)}).status_code == 401
        response = login(client, admin)
        cookie_header = response.headers['set-cookie']
        assert 'Secure' in cookie_header and 'HttpOnly' in cookie_header and 'SameSite=strict' in cookie_header
        token = client.cookies['__Host-mideagent_session']
        with db.connection() as conn:
            row = conn.execute('SELECT * FROM sessions WHERE token_hash=%s', (digest(token),)).fetchone()
            assert row and token not in str(row) and response.json()['csrf_token'] not in str(row)
        assert client.post('/api/accounts', json={'username': 'reader', 'password': admin[1]}, headers={'X-CSRF-Token': ''}).status_code == 403
        assert client.post('/api/accounts', json={'username': 'reader', 'password': admin[1]}, headers={'Origin': 'https://evil.invalid'}).status_code == 403
        assert client.post('/api/accounts', json={'username': 'reader', 'password': admin[1]}).status_code == 201
        accounts = client.get('/api/accounts').json()['accounts']
        assert len(accounts) == 2 and all('password' not in str(row) for row in accounts)
        malformed = client.post('/api/accounts', json={'username': 'other', 'password': admin[1], 'credential': 'synthetic-secret-never-echo'})
        assert malformed.status_code == 422 and 'synthetic-secret-never-echo' not in malformed.text and admin[1] not in malformed.text
        assert client.post('/api/auth/logout').status_code == 204
        assert client.get('/api/accounts').status_code == 401
        assert Accounts(db).session(token) is None
        login(client, ({'username': 'reader'}, admin[1]))
        assert client.get('/api/accounts').status_code == 403
        assert client.post('/api/accounts', json={'username': 'no-admin', 'password': admin[1]}).status_code == 403


def test_login_limit_json_bound_and_import_factory_does_not_migrate(db, admin):
    with app_client(db) as client:
        assert client.post('/api/auth/login', content='{}', headers={'Content-Type': 'text/plain'}).status_code == 415
        assert client.post('/api/auth/login', content=' ' * 65537, headers={'Content-Type': 'application/json'}).status_code == 413
        for _ in range(20):
            Accounts(db).throttle('synthetic-address')
        from video_service.auth import LoginThrottled
        with pytest.raises(LoginThrottled):
            Accounts(db).throttle('synthetic-address')
    class NoConnect:
        def connection(self):
            raise AssertionError('Factory must not connect or migrate')
    create_app(NoConnect(), allowed_origins=('http://testserver',))


def test_registry_owner_pinned_revision_conflict_immutable_and_availability(db, admin):
    owner = admin[0]['id']
    registry = Registry(db)
    connection_id, model_id = uuid4().hex, uuid4().hex
    first = registry.save_connection(owner, connection_id, revision=0, name='Local model endpoint',
            provider='openai_compatible', protocol='openai_compatible', endpoint='http://127.0.0.1:9000/deploy/v1')
    assert first['credential'] == 'not_set' and first['connection_verified'] is False
    assert registry.compatibility(owner, connection_id)['uses'] == ['translation']
    model = registry.save_model(owner, model_id, revision=0, name='Local text', model='local-model:latest',
            connection_id=connection_id, connection_revision=1, uses=['translation'])
    registry.save_connection(owner, connection_id, revision=1, name='Changed endpoint', provider='openai_compatible',
            protocol='openai_compatible', endpoint='http://127.0.0.1:9001/v1')
    assert registry.model(owner, model_id)['versions']['1']['connection_revision'] == 1
    with db.connection() as conn:
        assert conn.execute('SELECT endpoint FROM connection_revisions WHERE owner_id=%s AND connection_id=%s AND revision=1', (owner, connection_id)).fetchone()['endpoint'].endswith('/deploy/v1')
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.connection() as conn:
            conn.execute('UPDATE connection_revisions SET name=%s WHERE owner_id=%s AND connection_id=%s', ('mutation', owner, connection_id))
    with pytest.raises(Conflict):
        registry.save_connection(owner, connection_id, revision=0, name='Stale', provider='openai', protocol='openai', endpoint='https://example.invalid/v1')
    disabled = registry.availability(owner, model_id, revision=model['revision'], active=False)
    assert not disabled['active'] and disabled['current_revision'] == 1 and disabled['revision'] == 2
    with pytest.raises(Conflict):
        registry.availability(owner, model_id, revision=1, active=True)
    reader = Accounts(db).create('other-owner', secrets.token_urlsafe(24), actor_id=owner)
    assert registry.models(reader['id']) == []
    with pytest.raises(Missing):
        registry.model(reader['id'], model_id)
    with pytest.raises(Missing):
        registry.save_model(reader['id'], uuid4().hex, revision=0, name='Cross-owner', model='remote', connection_id=connection_id, connection_revision=1, uses=['translation'])
    with db.connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM registered_models WHERE owner_id=%s', (reader['id'],)).fetchone()['n'] == 0


def test_registry_api_round_trip_and_schema_rejection(db, admin):
    with app_client(db) as client:
        login(client, admin)
        cid, mid = uuid4().hex, uuid4().hex
        config = {'revision': 0, 'name': 'On-prem', 'provider': 'openai_compatible', 'protocol': 'openai_compatible', 'endpoint': 'http://127.0.0.1:9090/custom/v1'}
        assert client.put('/api/settings/serving-connections/' + cid, json=config).status_code == 200
        reread = client.get('/api/settings/serving-connections').json()['connections']
        assert reread[0]['id'] == cid and reread[0]['revision'] == 1
        assert client.post('/api/settings/registered-models/compatibility', json={'connection_id': cid, 'connection_revision': 1, 'model': 'anything'}).json()['verified'] is False
        config = {'revision': 0, 'name': 'Pinned local model', 'model': 'anything', 'connection_id': cid, 'connection_revision': 1, 'uses': ['translation']}
        assert client.put('/api/settings/registered-models/' + mid, json=config).status_code == 200
        assert client.get('/api/settings/registered-models').json()['models'][0]['versions']['1']['connection_id'] == cid
        assert client.put('/api/settings/registered-models/' + mid, json=config).status_code == 409
        config['revision'] = 1
        config['uses'] = ['transcription']
        assert client.put('/api/settings/registered-models/' + mid, json=config).status_code == 422
        assert client.get('/api/capabilities').json()['execution_enabled'] is False


@pytest.mark.parametrize('endpoint', ['http://user:pass@example.invalid/v1', 'http://169.254.169.254',
    'http://metadata.google.internal/v1', 'https://host/v1?key=secret', 'http://host/a/../b',
    'http://host/%2e%2e', 'http://host/path#', 'file:///etc/passwd', 'http://host\\evil', 'http://[::]/v1'])
def test_endpoint_rejection(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_openai_wire_prefix_no_key_echo_bounds_and_no_retry():
    requests = []
    def transport(request):
        requests.append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'my-local-model'}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'translated'}}]})
    adapter = OpenAITextAdapter('http://model.invalid/deploy/v1/', transport=httpx.MockTransport(transport), approved_origins={'http://model.invalid'})
    assert adapter.models() == ['my-local-model']
    assert adapter.chat('my-local-model', [{'role': 'user', 'content': 'hello'}]) == 'translated'
    assert [r.url.path for r in requests] == ['/deploy/v1/models', '/deploy/v1/chat/completions']
    assert 'authorization' not in requests[0].headers
    adapter.close()
    for response in [httpx.Response(503), httpx.Response(302, headers={'Location': 'http://other.invalid'}),
                     httpx.Response(200, json={'nested': {'synthetic-"key\\value': 'echo'}}), httpx.Response(200, content=b'x' * 262145)]:
        calls = []
        def failing(request):
            calls.append(request)
            assert request.headers['authorization'] == 'Bearer synthetic-"key\\value'
            return response
        adapter = OpenAITextAdapter('https://model.invalid/v1', api_key='synthetic-"key\\value', transport=httpx.MockTransport(failing), approved_origins={'https://model.invalid'})
        with pytest.raises(EndpointFailure) as error:
            adapter.models()
        assert len(calls) == 1 and 'synthetic-' not in str(error.value)
        adapter.close()


def test_production_frontend_http_postgres_roundtrip(db):
    if os.environ.get('MIDEAGENT_FRONTEND_ROUNDTRIP') != '1':
        pytest.skip('Explicit production frontend build + browser opt-in required')
    import pathlib
    import socket
    import subprocess
    import threading
    import time
    import uvicorn
    from starlette.staticfiles import StaticFiles
    root = pathlib.Path(__file__).resolve().parents[2]
    assert (root / 'apps/web/dist/index.html').is_file()
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    app = create_app(db, allowed_origins=(origin,), secure_cookies=False)
    app.mount('/', StaticFiles(directory=root / 'apps/web/dist', html=True))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, proxy_headers=False, lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, 'Isolated loopback HTTP test server did not start'
        import shutil
        node = shutil.which('node')
        assert node, 'Node.js is required for the explicit frontend roundtrip'
        result = subprocess.run([node, str(root / 'tests/renewal/frontend-roundtrip.mjs')],
                                env={**os.environ, 'MIDEAGENT_TEST_ORIGIN': origin}, capture_output=True, text=True, timeout=100)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), 'Isolated test API must terminate'
