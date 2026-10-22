"""Real loopback HTTP adapter contract, synthetic transcripts, disposable PG only."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
from test_foundation import admin as _admin
from test_foundation import db as _db

db, admin = _db, _admin
from test_model_profile import profile
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.registry import Registry


@pytest.fixture
def wire():
    calls = []
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            model = self.path.split('/models/')[-1].split(':')[0] if ':generateContent' in self.path else body['model']
            calls.append({'model': model, 'path': self.path, 'body': body, 'header_key': self.headers.get('x-goog-api-key'), 'authorization': self.headers.get('Authorization')})
            if model == 'cancel':
                entered.set()
                assert release.wait(10)
            code = 503 if model.startswith('fail') else 401 if model == 'auth' else 429 if model == 'rate-limit' else 200
            text = json.dumps(['통제된 번역'])
            response = ({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]} if ':generateContent' in self.path else {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]})
            data = json.dumps(response).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls, entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


def candidates(database, owner, store, origin, names):
    registry = Registry(database)
    result = []
    for index, name in enumerate(names):
        cid, mid = uuid4().hex, uuid4().hex
        protocol = 'gemini' if index == 0 else 'openai' if index == 1 else 'openai_compatible'
        registry.save_connection(owner, cid, revision=0, name=name, provider=protocol, protocol=protocol, endpoint=origin + ('/v1beta' if index == 0 else '/v1'))
        store.save(owner, cid, revision=1, secret='synthetic-' + name)
        registry.save_model(owner, mid, revision=0, name=name, model=name, connection_id=cid, connection_revision=2, **profile())
        result.append(dict(store.model(owner, mid, 1), owner_id=owner))
    return result


def test_real_http_finite_fallback_records_and_frozen_old_model(db, admin, wire):
    import importlib.util
    assert importlib.util.find_spec('video_service.postgres.translation') is not None, 'Registered translation runtime missing'
    from video_service.postgres import translation
    runtime_type = getattr(translation, 'TranslationRuntime', None)
    assert runtime_type is not None
    origin, calls, _, _ = wire
    owner = admin[0]['id']
    store = CredentialStore(db, os.urandom(32))
    pins = candidates(db, owner, store, origin, ['fail-gemini', 'fail-openai', 'success'])
    runtime = runtime_type(store, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    journal = []
    result = runtime.translate(pins, [{'start': 0, 'end': 1, 'text': 'Synthetic input'}],
                               source_language='en', target_language='ko', cancelled=lambda: False,
                               record=lambda attempts: journal.append(json.loads(json.dumps(attempts))))
    assert result['status'] == 'completed'
    assert [call['model'] for call in calls] == ['fail-gemini', 'fail-openai', 'success']
    assert [a['status'] for a in result['attempts']] == ['failed', 'failed', 'completed']
    assert result['selected']['model_id'] == pins[2]['model_id']
    assert result['segments'] == [{'start': 0, 'end': 1, 'text': '통제된 번역'}]
    assert calls[0]['header_key'] == 'synthetic-fail-gemini'
    assert 'source=en; target=ko' in calls[0]['body']['systemInstruction']['parts'][0]['text']
    assert any(a[-1]['status'] == 'started' for a in journal)


def test_translation_ticket_freezes_languages_candidates_and_executes(db, admin, wire, tmp_path):
    from test_execution import movie as movie_fixture
    from test_translation_chain import translation_graph
    from video_service.content_store import ContentStore
    from video_service.postgres.execution import Execution
    from video_service.postgres.translation import TranslationRuntime

    owner = admin[0]['id']
    origin, calls, _, _ = wire
    credentials = CredentialStore(db, os.urandom(32))
    pins = candidates(db, owner, credentials, origin, ['success'])
    (tmp_path / 'cas').mkdir()
    runtime = Execution(db, ContentStore(tmp_path / 'cas'))
    runtime.translation_runtime = TranslationRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    ref = {'model_id': pins[0]['model_id'], 'revision': 1}
    graph = runtime.save_definition(owner, uuid4().hex, translation_graph(ref))
    inspection = runtime.inspect(owner, graph['id'], graph['revision'])
    assert inspection['supported'], inspection['reasons']
    movie = movie_fixture.__wrapped__(tmp_path)
    source = runtime.ingest(owner, 'synthetic.mp4', movie)
    transcript = [{'start': 0, 'end': 0.5, 'text': 'Synthetic input'}]
    job = runtime.create(owner, source['asset_id'], graph['id'], graph['revision'], request_id=uuid4().hex,
                         options={'source_language': 'en', 'target_language': 'ko', 'transcript': transcript})
    assert job['snapshot']['model_bindings']['translate']['connection_revision'] == 2
    plan = runtime.plan(owner, job['id'])
    # Later heads/key rotation must not retarget the already-issued ticket.
    Registry(db).save_model(owner, ref['model_id'], revision=1, name='Later model', model='changed-after-ticket', connection_id=pins[0]['connection_id'], connection_revision=2, **profile())
    credentials.save(owner, pins[0]['connection_id'], revision=2, secret='synthetic-new-key-not-ticket')
    assert plan['ready'], plan['reasons']
    consent = runtime.confirm(owner, job['id'], plan['token'], uuid4().hex)
    runtime.admit(owner, job['id'], consent['id'], uuid4().hex)
    done = runtime.run_local(owner, job['id'])
    assert done['status'] == 'completed', done
    run = done['runs'][0]
    assert run['request']['translation']['source_language'] == 'en'
    assert run['request']['translation']['target_language'] == 'ko'
    assert run['result']['translation']['selected']['model_id'] == ref['model_id']
    output = json.loads(runtime.store.read(owner, run['result']['outputs']['transcript']))
    assert output == [{**transcript[0], 'text': '통제된 번역'}]
    assert len(calls) == 1
    assert 'synthetic-success' not in json.dumps(done, default=str)


def test_api_exposes_explicit_translation_runtime_without_maintenance_activation():
    import inspect

    from app.renewal import create_app
    assert 'translation_runtime' in inspect.signature(create_app).parameters


@pytest.mark.parametrize('names,expected,calls_expected', [
    (['fail-one'], 'failed', ['fail-one']),
    (['fail-one', 'fail-two', 'fail-three'], 'failed', ['fail-one', 'fail-two', 'fail-three']),
    (['success'], 'completed', ['success']),
    (['fail-one', 'success'], 'completed', ['fail-one', 'success']),
    (['auth', 'success'], 'failed', ['auth']),
    (['rate-limit', 'success'], 'completed', ['rate-limit', 'success']),
])
def test_no_fallback_all_failed_and_direct_success(db, admin, wire, names, expected, calls_expected):
    from video_service.postgres.translation import TranslationRuntime
    origin, calls, _, _ = wire
    credentials = CredentialStore(db, os.urandom(32))
    pins = candidates(db, admin[0]['id'], credentials, origin, names)
    runtime = TranslationRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    result = runtime.translate(pins, [{'start': 0, 'end': 1, 'text': 'Synthetic input'}], source_language='en', target_language='ko', cancelled=lambda: False, record=lambda _: None)
    assert result['status'] == expected
    assert [call['model'] for call in calls] == calls_expected
    assert len(result['attempts']) == len(calls_expected)


def test_cancellation_during_http_discards_result_and_never_advances(db, admin, wire):
    from concurrent.futures import ThreadPoolExecutor

    from video_service.postgres.translation import TranslationRuntime
    origin, calls, entered, release = wire
    credentials = CredentialStore(db, os.urandom(32))
    pins = candidates(db, admin[0]['id'], credentials, origin, ['cancel', 'success'])
    runtime = TranslationRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    stop = threading.Event()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(runtime.translate, pins, [{'start': 0, 'end': 1, 'text': 'Synthetic input'}], source_language='en', target_language='ko', cancelled=stop.is_set, record=lambda _: None)
        assert entered.wait(5)
        stop.set()
        release.set()
        result = future.result(5)
    assert result['status'] == 'cancelled'
    assert result['segments'] is None and result['selected'] is None
    assert [call['model'] for call in calls] == ['cancel']


@pytest.mark.parametrize('names', [['fail-one'], ['fail-one', 'fail-two', 'fail-three'], ['cancel', 'success']])
def test_ticket_failure_and_cancel_preserve_attempts_no_normal_output(db, admin, wire, tmp_path, names):
    from concurrent.futures import ThreadPoolExecutor

    from test_execution import movie
    from test_translation_chain import translation_graph
    from video_service.content_store import ContentStore
    from video_service.postgres.execution import Execution
    from video_service.postgres.translation import TranslationRuntime

    owner = admin[0]['id']
    origin, calls, entered, release = wire
    credentials = CredentialStore(db, os.urandom(32))
    pins = candidates(db, owner, credentials, origin, names)
    runtime = Execution(db, ContentStore(tmp_path), translation_runtime=TranslationRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http'))
    refs = [{'model_id': p['model_id'], 'revision': p['revision']} for p in pins]
    saved = runtime.save_definition(owner, uuid4().hex, translation_graph(refs[0], refs[1:]))
    source = runtime.ingest(owner, 'synthetic.mp4', movie.__wrapped__(tmp_path))
    job = runtime.create(owner, source['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex, options={'source_language': 'en', 'target_language': 'ko', 'transcript': [{'start': 0, 'end': 0.5, 'text': 'Synthetic input'}]})
    plan = runtime.plan(owner, job['id'])
    assert plan['ready'], plan['reasons']
    consent = runtime.confirm(owner, job['id'], plan['token'], uuid4().hex)
    runtime.admit(owner, job['id'], consent['id'], uuid4().hex)
    if names[0] == 'cancel':
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(runtime.run_local, owner, job['id'])
            assert entered.wait(5)
            current = runtime.get(owner, job['id'])
            assert current['runs'][0]['translation']['attempts'][0]['status'] == 'started'
            runtime.cancel(owner, job['id'], current['revision'])
            release.set()
            done = future.result(5)
        assert done['status'] == 'cancelled'
        assert [call['model'] for call in calls] == ['cancel']
        with db.connection() as conn:
            assert conn.execute('SELECT count(*) AS n FROM result_quarantine WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 1
    else:
        done = runtime.run_local(owner, job['id'])
        assert done['status'] == 'failed'
        assert [call['model'] for call in calls] == names
    assert done['runs'][0]['translation']['selected'] is None
    assert not (done['runs'][0]['result'] or {}).get('outputs')
    assert runtime.run_local(owner, job['id'])['status'] == done['status']
    assert len(calls) == (1 if names[0] == 'cancel' else len(names))
    if os.environ.get('MIDEAGENT_TRANSLATION_EVIDENCE'):
        from pathlib import Path
        directory = Path(os.environ['MIDEAGENT_TRANSLATION_EVIDENCE'])
        directory.mkdir(exist_ok=True, parents=True)
        (directory / ('ticket-' + '-'.join(names) + '.json')).write_text(json.dumps({
            'boundary': 'actual disposable PG + controlled loopback HTTP; not model quality/authentication',
            'ticket_id': done['id'], 'status': done['status'],
            'snapshot_sha256': done['snapshot_sha256'],
            'languages': {k: done['snapshot']['options'][k] for k in ['source_language', 'target_language']},
            'translation': done['runs'][0]['translation'],
            'http_models': [call['model'] for call in calls],
            'normal_outputs': (done['runs'][0]['result'] or {}).get('outputs', {}),
        }, ensure_ascii=False, indent=2))
