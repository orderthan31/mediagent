"""Real waiting projection/route over in-memory SQL; no PostgreSQL or services."""
import ast
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/orchestrator'))


class MemoryDatabase:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE jobs(owner_id TEXT,id TEXT,ticket_number INTEGER,status TEXT,snapshot TEXT,generation INTEGER,active_claim_id TEXT,cancel_requested BOOLEAN,library_removed_at TEXT);
        CREATE TABLE node_runs(owner_id TEXT,job_id TEXT,id TEXT,status TEXT,generation INTEGER,claim_id TEXT);
        CREATE TABLE broker_dispatch_queue(owner_id TEXT,job_id TEXT,node_run_id TEXT,agent_id TEXT,phase TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE message_outbox(owner_id TEXT,aggregate_id TEXT,id TEXT,published_at TEXT,payload TEXT);
        ''')
        self.calls = []

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql, params=()):
        self.calls.append(sql)
        if sql == 'SET TRANSACTION READ ONLY':
            return SimpleNamespace(fetchall=lambda: [])
        assert sql.lstrip().startswith(('WITH ', 'SELECT ')), 'read route must not mutate, lock, or capture observations'
        return self.db.execute(sql, params)

    def job(self, number, *, status='waiting', owner='a' * 32, claimed=True, removed=None):
        identity = f'{number:032x}'
        snapshot = {'asset': {'original_filename': f'literal file {number}.mp4', 'storage_key': 'PRIVATE KEY'}, 'definition': {'name': 'literal saved workflow'}, 'secret': 'PRIVATE MODEL REQUEST'}
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)', (owner, identity, number, status, json.dumps(snapshot), 1, 'PRIVATE CLAIM' if claimed else None, False, removed))
        return identity

    def delivery(self, job, suffix, *, phase='pending', owner='a' * 32, run_status='waiting', generation=1, claim='PRIVATE CLAIM', outbox=True, published=False):
        run = f'{suffix:032x}'
        self.db.execute('INSERT INTO node_runs VALUES(?,?,?,?,?,?)', (owner, job, run, run_status, generation, claim))
        self.db.execute('INSERT INTO broker_dispatch_queue VALUES(?,?,?,?,?,?,?)', (owner, job, run, 'encode', phase, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00'))
        if outbox:
            self.db.execute('INSERT INTO message_outbox VALUES(?,?,?,?,?)', (owner, job, run, '2026-01-01' if published else None, 'PRIVATE PAYLOAD'))


@pytest.fixture
def database():
    value = MemoryDatabase()
    yield value
    value.db.close()


def actual_runtime(database):
    path = ROOT / 'apps/orchestrator/mideagent_orchestrator/execution.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == 'Execution')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execution_waiting']
    assert len(methods) == 1, 'real Execution waiting read entry is missing'
    namespace = {'__package__': 'mideagent_orchestrator'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Actual', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])), str(path), 'exec'), namespace)
    runtime = namespace['Actual']()
    runtime.database = database
    return runtime


def actual_app(runtime, *, authenticated=True, actor='a' * 32):
    from fastapi import Depends, FastAPI, HTTPException
    path = ROOT / 'apps/api/app/renewal_routes.py'
    mount = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'mount_runtime')
    functions = [n for n in mount.body if isinstance(n, ast.FunctionDef) and n.name in {'owner', 'execution_waiting'}]
    assert len(functions) == 2, 'protected real waiting handler is missing'
    assignments = [n for n in mount.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'session_dependency', 'owner_dependency'} for t in n.targets)]
    nodes = sorted([*functions, *assignments], key=lambda n: n.lineno)
    app = FastAPI()
    def session():
        if not authenticated:
            raise HTTPException(401, 'unit authentication required')
        return {'user': {'id': actor}}
    namespace = {'Depends': Depends, 'app': app, 'runtime': runtime, 'session': session}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return app


def get(app):
    async def request():
        sent = []
        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        async def send(value):
            sent.append(value)
        await app({'type': 'http', 'http_version': '1.1', 'method': 'GET', 'scheme': 'https', 'path': '/api/renewal/execution-waiting', 'raw_path': b'/api/renewal/execution-waiting', 'query_string': b'', 'headers': [], 'client': ('unit', 1), 'server': ('unit', 443), 'root_path': ''}, receive, send)
        return sent[0]['status'], json.loads(b''.join(row.get('body', b'') for row in sent))
    return asyncio.run(request())


def test_actual_protected_route_reads_dispatch_not_ledger_waiting(database):
    pending = database.job(1)
    database.delivery(pending, 100)
    database.job(32)  # Already admitted but no run/outbox/dispatch; never a queue member.
    database.job(33, claimed=False)
    database.job(34, status='draft', claimed=False)
    before = list(database.db.iterdump())
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 200 and [row['job_id'] for row in body['jobs']] == [pending]
    item = body['jobs'][0]
    assert item['deliveries'] == [{'phase': 'pending', 'run_status': 'waiting', 'count': 1}]
    assert item['access'] == {'can_manage': True}
    assert item['ticket_number'] == '1' and item['original_filename'] == 'literal file 1.mp4'
    assert item['workflow_name'] == 'literal saved workflow'
    assert 'PRIVATE' not in json.dumps(body)
    assert set(item) == {'job_id', 'ticket_number', 'status', 'original_filename', 'workflow_name', 'queued_at', 'deliveries', 'access'}
    assert before == list(database.db.iterdump())
    assert database.calls[0] == 'SET TRANSACTION READ ONLY' and len(database.calls) == 2


def test_unauthenticated_route_does_not_read_database(database):
    status, _ = get(actual_app(actual_runtime(database), authenticated=False))
    assert status == 401 and database.calls == []


def test_native_deliveries_are_grouped_without_collapsing_different_states(database):
    job = database.job(2)
    database.delivery(job, 200, phase='pending')
    database.delivery(job, 201, phase='pending')
    for number, phase in enumerate(('sending', 'sent', 'received', 'unknown'), 202):
        database.delivery(job, number, phase=phase, run_status='running')
    body = actual_runtime(database).execution_waiting('b' * 32)
    assert len(body['jobs']) == 1 and body['jobs'][0]['access'] == {'can_manage': False}
    assert body['jobs'][0]['deliveries'] == [
        {'phase': 'pending', 'run_status': 'waiting', 'count': 2},
        *({'phase': phase, 'run_status': 'running', 'count': 1} for phase in ('sending', 'sent', 'received', 'unknown')),
    ]
    assert body['has_more'] is False and body['limit'] == 100


@pytest.mark.parametrize('invalid', ['unadmitted', 'draft', 'generation', 'claim', 'outbox_missing', 'published', 'cancel_requested', 'removed', 'completed', 'cancelled_phase'])
def test_only_current_pending_attempts_are_reported(database, invalid):
    job = database.job(5, status='draft' if invalid == 'draft' else 'waiting', claimed=invalid != 'unadmitted', removed='2026-01-01' if invalid == 'removed' else None)
    database.delivery(job, 500, generation=2 if invalid == 'generation' else 1,
                      claim='other claim' if invalid == 'claim' else 'PRIVATE CLAIM',
                      outbox=invalid != 'outbox_missing', published=invalid == 'published',
                      run_status='completed' if invalid == 'completed' else 'waiting',
                      phase='cancelled' if invalid == 'cancelled_phase' else 'pending')
    if invalid == 'cancel_requested':
        database.db.execute('UPDATE jobs SET cancel_requested=true')
    assert actual_runtime(database).execution_waiting('a' * 32)['jobs'] == []


def test_unknown_survives_old_generation_and_failed_status_without_replay(database):
    job = database.job(6, status='failed', claimed=False)
    database.delivery(job, 600, phase='unknown', run_status='failed', generation=0)
    before = list(database.db.iterdump())
    body = actual_runtime(database).execution_waiting('a' * 32)
    assert body['jobs'][0]['deliveries'] == [{'phase': 'unknown', 'run_status': 'failed', 'count': 1}]
    assert list(database.db.iterdump()) == before


def test_bounded_job_selection_keeps_every_state_for_the_last_visible_job(database):
    for number in range(1, 103):
        job = database.job(number)
        database.delivery(job, number + 1000)
        if number == 100:
            database.delivery(job, 5000, phase='unknown', run_status='failed')
    body = actual_runtime(database).execution_waiting('a' * 32)
    assert body['has_more'] is True and len(body['jobs']) == 100
    assert len(body['jobs'][-1]['deliveries']) == 2


def test_query_failure_is_not_a_confirmed_empty_list(database):
    runtime = actual_runtime(database)
    database.db.execute('DROP TABLE broker_dispatch_queue')
    with pytest.raises(sqlite3.OperationalError):
        runtime.execution_waiting('a' * 32)


def test_ambiguous_shared_identity_fails_without_a_misleading_detail_link(database):
    job = database.job(7)
    database.delivery(job, 700)
    database.job(7, owner='b' * 32)
    with pytest.raises(ValueError, match='식별자'):
        actual_runtime(database).execution_waiting('a' * 32)


def test_authenticated_shared_reader_gets_existing_detail_identity_without_manage_rights(database):
    job = database.job(8)
    database.delivery(job, 800)
    status, body = get(actual_app(actual_runtime(database), actor='b' * 32))
    assert status == 200 and body['jobs'][0]['job_id'] == job
    assert body['jobs'][0]['access'] == {'can_manage': False}


@pytest.mark.parametrize('phase', ['sent', 'received'])
def test_confirmed_terminal_run_is_not_active_delivery_waiting(database, phase):
    job = database.job(9, status='completed')
    database.delivery(job, 900, phase=phase, run_status='completed', published=True)
    assert actual_runtime(database).execution_waiting('a' * 32)['jobs'] == []


def test_confirmed_sent_failure_is_not_delivery_waiting_before_cleanup(database):
    job = database.job(10, status='failed')
    database.delivery(job, 10000, phase='sent', run_status='failed', published=True)
    before = list(database.db.iterdump())
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 200 and body['jobs'] == []
    assert before == list(database.db.iterdump())


def test_confirmed_received_failure_is_not_delivery_waiting_before_cleanup(database):
    job = database.job(11, status='failed')
    database.delivery(job, 11000, phase='received', run_status='failed', published=True)
    before = list(database.db.iterdump())
    status, body = get(actual_app(actual_runtime(database)))
    assert status == 200 and body['jobs'] == []
    assert before == list(database.db.iterdump())


def test_failure_filter_does_not_broaden_sending_or_pending_behavior(database):
    job = database.job(12)
    database.delivery(job, 12000, phase='pending', run_status='waiting')
    database.delivery(job, 12001, phase='pending', run_status='failed')
    database.delivery(job, 12002, phase='sending', run_status='waiting')
    database.delivery(job, 12003, phase='sending', run_status='failed')
    before = list(database.db.iterdump())
    body = actual_runtime(database).execution_waiting('a' * 32)
    assert body['jobs'][0]['deliveries'] == [
        {'phase': 'pending', 'run_status': 'waiting', 'count': 1},
        {'phase': 'sending', 'run_status': 'failed', 'count': 1},
        {'phase': 'sending', 'run_status': 'waiting', 'count': 1},
    ]
    assert before == list(database.db.iterdump())
