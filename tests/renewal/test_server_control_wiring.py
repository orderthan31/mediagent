"""Production entrypoint wiring, without enrolling or running a native target."""
import json
import secrets
import socket
import subprocess
import sys
import time

import httpx
from test_foundation import db as _db_fixture

db = _db_fixture


def test_production_server_control_routes_without_targets(db, tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    (tmp_path / 'dsn').write_text(db.dsn)
    (tmp_path / 'content').mkdir()
    config = tmp_path / 'api.json'
    config.write_text(json.dumps({
        'database_dsn_file': str(tmp_path / 'dsn'),
        'content_root': str(tmp_path / 'content'),
        'allowed_origins': [origin], 'host': '127.0.0.1', 'port': port,
        'secure_cookies': False,
    }))
    process = subprocess.Popen([
        sys.executable, '-m', 'app.server', '--bootstrap-file', str(config),
        '--enable-control',
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=origin, timeout=3) as client:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError('Production entrypoint could not enable control API wiring')
                try:
                    if client.get('/healthz').status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(.05)
            else:
                raise AssertionError('Production entrypoint was not ready')
            route = '/api/admin/agents/encode/recovery'
            assert client.get(route).status_code == 401
            password = secrets.token_urlsafe(32)
            assert client.post('/api/auth/bootstrap', json={
                'username': 'wiring-admin', 'password': password,
            }).status_code == 201
            login = client.post('/api/auth/login', json={
                'username': 'wiring-admin', 'password': password,
            })
            assert login.status_code == 200
            headers = {'Origin': origin, 'X-CSRF-Token': login.json()['csrf_token']}
            status = client.get(route)
            assert status.status_code == 200
            assert status.json()['registered'] is False
            assert status.json()['history'] == []
            assert status.json()['unavailable_reason'] == 'control_target_not_registered'
            assert client.post(route + '/preview', json={}).status_code == 403
            assert client.post(route + '/preview', json={}, headers=headers).status_code == 404
            agent = client.get('/api/admin/agents/encode').json()
            assert agent['control_available'] is True
            assert agent['control_registered'] is False
            assert agent['manageable'] is False
            assert client.post('/api/accounts', json={
                'username': 'wiring-reader', 'password': password,
            }, headers=headers).status_code == 201
            login = client.post('/api/auth/login', json={
                'username': 'wiring-reader', 'password': password,
            })
            assert login.status_code == 200
            assert client.get(route).status_code == 403
        with db.connection() as connection:
            assert connection.execute('SELECT count(*) AS n FROM remote_control_groups').fetchone()['n'] == 0
            assert connection.execute('SELECT count(*) AS n FROM remote_control_requests').fetchone()['n'] == 0
    finally:
        process.terminate()
        out, err = process.communicate(timeout=10)
        assert db.dsn.encode() not in out + err
