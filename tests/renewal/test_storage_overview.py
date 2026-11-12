"""Actual protected aggregate and resource handlers, with memory SQL/ASGI only."""
import ast
import asyncio
from contextlib import contextmanager
import json
import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


class QueryError(Exception):
    pass


class Conflict(Exception):
    pass


class MemoryDatabase:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE assets(owner_id TEXT,id TEXT,bytes INTEGER,sha256 TEXT,library_removed_at TEXT)')
        self.calls = []
        self.fail = False

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql):
        self.calls.append(sql)
        if sql == 'SET TRANSACTION READ ONLY':
            return SimpleNamespace()
        if self.fail:
            raise QueryError('PRIVATE DSN/path/credential')
        assert sql.lstrip().startswith('SELECT '), 'no writes or locks'
        return self.db.execute(sql)

    def asset(self, owner, identity, size, *, removed=None, sha='same-cas'):
        self.db.execute('INSERT INTO assets VALUES(?,?,?,?,?)', (owner, identity, size, sha, removed))


@pytest.fixture
def database():
    value = MemoryDatabase()
    yield value
    value.db.close()


def actual_runtime(database):
    path = ROOT / 'packages/shared/video_service/postgres/intake.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Intake')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'storage_overview']
    assert len(methods) == 1, 'actual read-only shared storage aggregate is missing'
    namespace = {'Conflict': Conflict}
    node = ast.ClassDef(name='Actual', bases=[], keywords=[], body=methods, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), namespace)
    runtime = namespace['Actual']()
    runtime.database = database
    return runtime


def actual_app(runtime, *, authenticated=True, actor='ordinary-user'):
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    path = ROOT / 'apps/api/app/renewal_routes.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    mount = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mount_runtime')
    nodes = [n for n in mount.body if isinstance(n, ast.FunctionDef) and n.name in {'owner', 'storage_overview'}]
    assert len(nodes) == 2, 'actual protected storage route is missing'
    nodes += [n for n in mount.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'session_dependency', 'owner_dependency'} for t in n.targets)]
    app = FastAPI()

    def session():
        if not authenticated:
            raise HTTPException(401, 'unit authentication required')
        return {'user': {'id': actor}}

    namespace = {'Depends': Depends, 'app': app, 'runtime': runtime, 'session': session}
    exec(compile(ast.Module(body=sorted(nodes, key=lambda n: n.lineno), type_ignores=[]), str(path), 'exec'), namespace)
    # Reuse the existing production PG failure response, without importing DB/runtime.
    tree = ast.parse((ROOT / 'apps/api/app/renewal.py').read_text(encoding='utf-8'))
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'unavailable')
    handler.decorator_list = []
    namespace = {'JSONResponse': JSONResponse}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), 'renewal.py', 'exec'), namespace)
    app.add_exception_handler(QueryError, namespace['unavailable'])
    return app


def get(app, path='/api/renewal/storage-overview'):
    async def request():
        sent = []
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(value):
            sent.append(value)
        await app({'type': 'http', 'http_version': '1.1', 'method': 'GET', 'scheme': 'https', 'path': path, 'raw_path': path.encode(), 'query_string': b'', 'headers': [], 'client': ('unit', 1), 'server': ('unit', 443), 'root_path': ''}, receive, send)
        return sent[0]['status'], json.loads(b''.join(row.get('body', b'') for row in sent))
    return asyncio.run(request())


def test_actual_route_exact_shared_totals_no_deduplication_or_writes(database):
    database.asset('user-a', 'a', 1024)
    database.asset('user-b', 'b', 2048)  # Same CAS is two registrations, not physical usage.
    database.asset('user-c', 'a', 4096, removed='2026-01-01')
    before = list(database.db.iterdump())
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 200
    assert body['originals'] == {'count': '2', 'bytes': '3072'}
    assert set(body) == {'originals', 'observed_at'}
    assert body['observed_at'].endswith('+00:00')
    assert 'same-cas' not in json.dumps(body) and 'user-' not in json.dumps(body)
    assert database.calls[0] == 'SET TRANSACTION READ ONLY' and len(database.calls) == 2
    assert before == list(database.db.iterdump())


def test_unauthenticated_no_read(database):
    assert get(actual_app(actual_runtime(database), authenticated=False))[0] == 401
    assert database.calls == []


def test_zero_is_confirmed_and_counts_are_decimal_strings(database):
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 200 and body['originals'] == {'count': '0', 'bytes': '0'}
    database.asset('a', 'huge', 9007199254740993)
    assert get(actual_app(actual_runtime(database)))[1]['originals']['bytes'] == '9007199254740993'


def test_query_failure_is_503_not_zero_or_secret(database):
    database.fail = True
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 503 and 'originals' not in body and 'PRIVATE' not in json.dumps(body)


def test_ambiguous_shared_ids_preserve_library_conflict(database):
    database.asset('a', 'duplicate', 1)
    database.asset('b', 'duplicate', 2)
    with pytest.raises(Conflict):
        actual_runtime(database).storage_overview('a')


def resource_app(monkeypatch, payload, *, authenticated=True):
    from fastapi import FastAPI, HTTPException
    path = ROOT / 'apps/api/app/system_resource_routes.py'
    spec = importlib.util.spec_from_file_location('unit_storage_resources', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reads = []

    def trusted_path(value):
        assert value == '/run/host-status/resources.json'
        reads.append(value)
        def read_bytes():
            if isinstance(payload, Exception):
                raise payload
            return payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return SimpleNamespace(read_bytes=read_bytes)

    monkeypatch.setattr(module, 'Path', trusted_path)
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda: 1000))

    def session():
        if not authenticated:
            raise HTTPException(401, 'unit authentication required')
        return {'user': {'id': 'unit'}}

    app = FastAPI()
    module.mount_system_resources(app, session)
    return app, reads


def test_existing_resource_contract_bytes_and_time_no_alternative_disk_probe(monkeypatch):
    payload = {'observed_unix': 999, 'observed_at': '2026-01-01T00:00:00Z', 'nodes': [],
               'storage': [{'name': 'Object storage', 'total': 1024, 'free': 512, 'source': 'Connected object volume', 'status': 'connected'}]}
    app, reads = resource_app(monkeypatch, payload)
    status, body = get(app, '/api/system/resources')
    assert status == 200 and body['status'] == 'connected'
    assert body['storage'] == payload['storage'] and body['observed_at'] == payload['observed_at']
    assert body['age_seconds'] == 1 and len(reads) == 1


def test_resource_unauthenticated_does_not_read_collector(monkeypatch):
    app, reads = resource_app(monkeypatch, {}, authenticated=False)
    assert get(app, '/api/system/resources')[0] == 401 and reads == []


def test_stale_resource_never_represents_old_capacity_as_current(monkeypatch):
    app, _ = resource_app(monkeypatch, {'observed_unix': 1, 'observed_at': 'old-observation', 'storage': [{'total': 123, 'free': 45}]})
    status, body = get(app, '/api/system/resources')
    assert status == 200 and body['status'] == 'stale'
    assert body['observed_at'] == 'old-observation' and body['storage'] == []


@pytest.mark.parametrize('payload', [FileNotFoundError('PRIVATE path'), b'invalid-json', b'x' * 65537, {}])
def test_absent_or_invalid_resource_is_unknown_not_zero(monkeypatch, payload):
    app, reads = resource_app(monkeypatch, payload)
    status, body = get(app, '/api/system/resources')
    assert status == 200 and body['status'] == 'unavailable' and body['storage'] == []
    assert 'PRIVATE' not in json.dumps(body) and len(reads) == 1
