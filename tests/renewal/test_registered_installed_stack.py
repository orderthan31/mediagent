"""Opt-in installed CLI boundary on disposable PG, real TLS RabbitMQ/MinIO.

Run only with REG_INSTALLED_BOOTSTRAP_ROOT and MIDEAGENT_TEST_DISPOSABLE=1.
The controlled provider is loopback HTTP; it does not recognize/translate media.
API and application consumers are independent installed processes. CPU workers
are separate existing immutable images on this fixture's internal-only network.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from app.operator import runtime_components
from app.server import load_bootstrap
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from test_execution import movie
from test_transcription_execution import audio_graph
from video_service.cpu_agents import canonical, digest
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.rabbitmq_transport import Delivery
from video_service.registered_broker import COMMAND, decode_reference


def until(read, predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        time.sleep(0.05)
    raise AssertionError('Installed boundary did not reach the required state')


@pytest.fixture(scope='module')
def installed():
    root_value = os.environ.get('REG_INSTALLED_BOOTSTRAP_ROOT')
    if not root_value:
        pytest.skip('Explicit isolated installed bootstrap required')
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    root = Path(root_value)
    config, dsn = load_bootstrap(root / 'seed.json')
    target = conninfo_to_dict(dsn)
    assert target['host'] == 'registered-db' and target['dbname'] == 'registered_fixture'
    schema = target['options'].removeprefix('-c search_path=')
    assert re.fullmatch('registered_[a-z0-9_]{1,40}', schema)
    assert os.getuid() == 10001
    with psycopg.connect(dsn) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    database = Database(dsn)
    database.migrate()
    private = json.loads((root / 'fixture-secrets.json').read_text())
    actor = Accounts(database).create('registered-install-admin', private['password'], first=True)
    store, credentials, factory = runtime_components(database, config, enable_broker=True,
        enable_registered=True, allow_controlled_models=True)
    runtime = Execution(database, store, translation_runtime=factory.translation_runtime,
                        transcription_runtime=factory.transcription_runtime)
    registry = Registry(database)
    refs, definitions, processes, handles, exits, calls, errors = {}, {}, {}, {}, {}, [], []
    entered, release = threading.Event(), threading.Event()
    stop_event = threading.Event()
    evidence = Path(os.environ['REG_INSTALLED_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    private_logs = Path(os.environ['REG_INSTALLED_PRIVATE_LOGS'])
    private_logs.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'MIDEAGENT_TEST_DSN'}}

    def start(name, module, *args, enabled=True):
        path = root / ('api.json' if module == 'app.server' else 'worker.json' if name.startswith('model') else 'results.json')
        command = [sys.executable, '-m', module, *args, '--bootstrap-file', str(path), '--enable-broker']
        if enabled:
            command += ['--enable-registered-models', '--allow-controlled-models']
        handles[name] = (private_logs / (name + '.log')).open('wb')
        processes[name] = subprocess.Popen(command, env=env, stdout=handles[name], stderr=subprocess.STDOUT)
        return processes[name]

    def stop(name):
        process = processes[name]
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        exits[name] = process.wait(timeout=30)
        handles[name].close()

    def request(client, method, path, value=None, expected=200):
        response = client.request(method, path, json=value if value is not None else {}) if value is not None or method == 'POST' else client.request(method, path)
        assert response.status_code == expected, (path, response.status_code)
        return response.json()

    def client_for_api(enabled):
        start('api', 'app.server', '--admission-mode', 'normal', enabled=enabled)
        client = httpx.Client(base_url='http://127.0.0.1:9418', headers={'Origin': 'http://127.0.0.1:9418'}, trust_env=False, timeout=5)
        def healthy():
            if processes['api'].poll() is not None:
                raise AssertionError('Installed API process exited')
            try:
                return client.get('/healthz').status_code == 200
            except httpx.TransportError:
                return False
        until(healthy, bool)
        reply = request(client, 'POST', '/api/auth/login', {'username': actor['username'], 'password': private['password']})
        client.headers['X-CSRF-Token'] = reply['csrf_token']
        return client

    # Immutable registration prerequisites, not a new provider-registration test.
    for name, protocol, speech in [('asr_first', 'gemini', True), ('asr_second', 'openai', True),
                                   ('text_first', 'openai', False), ('text_second', 'gemini', False),
                                   ('cancel_first', 'gemini', True)]:
        cid, mid = uuid4().hex, uuid4().hex
        endpoint = 'http://127.0.0.1:9419/' + name + '/v1'
        registry.save_connection(actor['id'], cid, revision=0, name=name, provider=protocol, protocol=protocol, endpoint=endpoint)
        credentials.save(actor['id'], cid, revision=1, secret=private['keys'][name])
        registry.save_model(actor['id'], mid, revision=0, name=name,
            model='whisper-1' if speech and protocol == 'openai' else 'gemini-fixture' if protocol == 'gemini' else 'fixture-chat',
            connection_id=cid, connection_revision=2, model_types=['speech_recognition' if speech else 'text'],
            input_modalities=['audio' if speech else 'text'], output_modalities=['text'],
            capabilities=['speech_recognition' if speech else 'text_generation'])
        refs[name] = {'model_id': mid, 'revision': 1}
    for name, first in [('success', 'asr_first'), ('cancel', 'cancel_first')]:
        graph = audio_graph(refs[first], refs['text_first'], [refs['asr_second']])
        graph['nodes'][-1]['fallback_refs'] = [refs['text_second']]
        definitions[name] = runtime.save_definition(actor['id'], uuid4().hex, graph)
    with tempfile.TemporaryDirectory() as temporary:
        source = runtime.ingest(actor['id'], 'installed-synthetic.mp4', movie.__wrapped__(Path(temporary)))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            name = self.path.split('/')[1]
            raw = self.rfile.read(int(self.headers['Content-Length']))
            key = self.headers.get('x-goog-api-key') or self.headers.get('Authorization', '').removeprefix('Bearer ')
            matched = name in private['keys'] and hmac.compare_digest(key, private['keys'][name])
            if not matched:
                errors.append('credential_or_endpoint_pin_changed')
                self.send_error(401)
                return
            kind = 'transcription' if name.startswith(('asr_', 'cancel_')) else 'translation'
            body, audio, language, target_language = {}, b'', None, None
            if 'multipart/form-data' in self.headers.get('Content-Type', ''):
                message = BytesParser(policy=default).parsebytes(('Content-Type: ' + self.headers['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
                form = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True) for part in message.iter_parts()}
                audio, language = form['file'], form['language'].decode()
                remote_model = form['model'].decode()
                assert form['model'] == b'whisper-1' and form['response_format'] == b'verbose_json'
            else:
                body = json.loads(raw)
                remote_model = body.get('model') or re.search(r'/models/([^/:]+):generateContent$', self.path)[1]
                instruction = body.get('systemInstruction', {}).get('parts', [{}])[0].get('text', '')
                if kind == 'transcription':
                    audio = base64.b64decode(body['contents'][0]['parts'][0]['inlineData']['data'])
                    language = re.search(r'Language=([a-z]+)', instruction)[1]
                else:
                    instruction = instruction or body['messages'][0]['content']
                    language = re.search(r'source=([a-z]+)', instruction)[1]
                    target_language = re.search(r'target=([a-z]+)', instruction)[1]
            with database.connection() as db:
                rows = db.execute('SELECT d.node_run_id,d.command_sha256,d.result,n.request FROM agent_deliveries d JOIN node_runs n ON n.owner_id=d.owner_id AND n.job_id=d.job_id AND n.id=d.node_run_id WHERE d.owner_id=%s AND d.status=\'started\'', (actor['id'],)).fetchall()
            matching = [row for row in rows if (row['result'] or {}).get(kind, {}).get('attempts', [{}])[-1].get('model_id') == refs[name]['model_id']]
            assert len(matching) == 1, 'Committed pre-HTTP candidate intent missing'
            row = matching[0]
            attempt = row['result'][kind]['attempts'][-1]
            assert attempt['status'] == 'started' and attempt['connection_revision'] == 2
            pin = row['request'][kind]['candidates'][attempt['index']]
            assert remote_model == pin['remote_model']
            suffix = '/models/'+remote_model+':generateContent' if pin['protocol']=='gemini' else '/audio/transcriptions' if kind=='transcription' else '/chat/completions'
            assert self.path == urlsplit(pin['endpoint']).path + suffix
            assert language == row['request'][kind]['source_language']
            if kind == 'translation':
                assert target_language == row['request'][kind]['target_language']
            calls.append({'name': name, 'kind': kind, 'path': self.path, 'key_pin_match': matched,
                          'remote_model': remote_model, 'endpoint_pin_match': True,
                          'language': language, 'target_language': target_language,
                          'audio_sha256': hashlib.sha256(audio).hexdigest() if audio else None,
                          'node_run_id': row['node_run_id'], 'request_sha256': row['command_sha256'],
                          'model_id': attempt['model_id'], 'connection_revision': attempt['connection_revision'],
                          'intent_committed': True})
            if name == 'cancel_first':
                entered.set()
                assert release.wait(12), 'Cancellation release missing'
            status = 503 if name in {'asr_first', 'text_first', 'cancel_first'} else 200
            values = [{'start': 0.1, 'end': 0.4, 'text': 'Installed controlled speech'}]
            if name == 'text_second':
                content = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(['설치 연결 통과'], ensure_ascii=False)}]}}]}
            elif self.headers.get('Content-Type', '').startswith('multipart/'):
                content = {'segments': values}
            else:
                content = {'error': {'code': 'CONTROLLED_UPSTREAM_FAILURE'}}
            data = json.dumps(content, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    provider = ThreadingHTTPServer(('127.0.0.1', 9419), Handler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    fixture = SimpleNamespace(root=root, private=private, database=database, runtime=runtime, factory=factory,
        owner=actor['id'], credentials=credentials, registry=registry, refs=refs, definitions=definitions,
        source=source, calls=calls, errors=errors, start=start, stop=stop, processes=processes,
        request=request, client_for_api=client_for_api, entered=entered, release=release,
        evidence=evidence, exits=exits, stop_event=stop_event)
    start('results', 'app.operator', 'consume-results')
    try:
        yield fixture
    finally:
        release.set()
        for name in reversed(list(processes)):
            if not handles[name].closed:
                stop(name)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(5)
        with database.connection() as db:
            state = {'jobs': db.execute('SELECT id,status,generation FROM jobs ORDER BY id').fetchall(),
                     'outbox': db.execute('SELECT id,message_type,published_at IS NOT NULL AS published FROM message_outbox ORDER BY id').fetchall(),
                     'deliveries': db.execute('SELECT node_run_id,status FROM agent_deliveries ORDER BY node_run_id').fetchall()}
        report = {'requests': calls, 'errors': errors, 'process_exit_codes': exits, 'state': state,
                  'scope': 'isolated installed CLI/PG/TLS MQ/TLS MinIO; controlled loopback responses, not supplier authentication or quality'}
        text = json.dumps(report, ensure_ascii=False, default=str)
        assert all(value not in text for value in [private['password'], *private['keys'].values(), *private['rotated'].values()])
        (evidence / 'installed-stack.json').write_text(text)


def create_and_admit(stack, client, name):
    definition = stack.definitions[name]
    selection = {'asset_id': stack.source['asset_id'], 'definition_id': definition['id'],
                 'definition_revision': definition['revision'], 'options': {'source_language': 'en', 'target_language': 'ko'}}
    preview = stack.request(client, 'POST', '/api/work-entry/preview', selection)
    job = stack.request(client, 'POST', '/api/work-entry/create', {**selection, 'token': preview['token'], 'request_id': uuid4().hex}, expected=201)
    path = '/api/renewal/jobs/' + job['id']
    plan = stack.request(client, 'GET', path + '/plan')
    assert plan['ready']
    consent = stack.request(client, 'POST', path + '/confirm', {'token': plan['token'], 'request_id': uuid4().hex})
    stack.request(client, 'POST', path + '/admit', {'consent_id': consent['id'], 'request_id': uuid4().hex})
    return job, path


def test_installed_api_default_keeps_registered_execution_disabled(installed):
    stack = installed
    client = stack.client_for_api(False)
    try:
        definition = stack.definitions['success']
        value = stack.request(client, 'POST', '/api/work-entry/inspect', {'definition_id': definition['id'], 'definition_revision': definition['revision']})
        assert value['supported'] is False and value['model_ready'] is False
        assert stack.calls == []
    finally:
        client.close()
        stack.stop('api')


def test_official_entry_to_registered_mq_request_receipt_manifest_download(installed):
    stack = installed
    client = stack.client_for_api(True)
    try:
        job, path = create_and_admit(stack, client, 'success')
        # Change heads only in this fresh fixture AFTER the real API froze the ticket.
        for name in ('asr_first', 'asr_second', 'text_first', 'text_second'):
            pin = stack.credentials.model(stack.owner, stack.refs[name]['model_id'], 1)
            stack.credentials.save(stack.owner, pin['connection_id'], revision=2, secret=stack.private['rotated'][name])
            stack.registry.save_connection(stack.owner, pin['connection_id'], revision=3, name='later-'+name,
                provider=pin['protocol'], protocol=pin['protocol'], endpoint='http://127.0.0.1:9419/later_'+name+'/v2')
            stack.registry.save_model(stack.owner, pin['model_id'], revision=1, name='later-'+name,
                model='gemini-replaced' if pin['protocol']=='gemini' else 'replaced',
                connection_id=pin['connection_id'], connection_revision=4, model_types=pin['model_types'],
                input_modalities=pin['input_modalities'], output_modalities=pin['output_modalities'], capabilities=pin['capabilities'])
        started = time.monotonic()
        stack.request(client, 'POST', path + '/run')
        assert time.monotonic() - started < 5 and stack.calls == []
        def pending():
            with stack.factory.registered_factory() as broker:
                method, properties, body = broker.channel.basic_get(broker.config.queue('registered'), auto_ack=False)
                if method is None:
                    return None
                delivery = Delivery(body=body, message_type=properties.type, message_id=properties.message_id,
                    correlation_id=properties.correlation_id, content_type=properties.content_type,
                    content_encoding=properties.content_encoding)
                broker.channel.basic_nack(method.delivery_tag, requeue=True)
                return delivery
        delivery = until(pending, lambda value: value is not None, seconds=12)
        ref = decode_reference(delivery)
        assert set(json.loads(delivery.body)) == {'version', 'owner', 'job_id', 'attempt_id', 'request_sha256'}
        assert ref['job_id'] == job['id'] and stack.calls == []
        stack.start('model', 'app.operator', 'consume-registered-models')
        done = until(lambda: stack.request(client, 'GET', path), lambda value: value['status'] in {'completed', 'failed'})
        assert done['status'] == 'completed'
        assert [call['name'] for call in stack.calls] == ['asr_first', 'asr_second', 'text_first', 'text_second']
        assert all(call['language'] == 'en' and call['key_pin_match'] and call['intent_committed'] for call in stack.calls)
        assert all(call['target_language'] == 'ko' for call in stack.calls if call['kind'] == 'translation')
        asr = next(run for run in done['runs'] if run['node_type'] == 'transcribe')
        text = next(run for run in done['runs'] if run['node_type'] == 'translate')
        assert [attempt['status'] for attempt in asr['result']['transcription']['attempts']] == ['failed', 'completed']
        assert [attempt['status'] for attempt in text['result']['translation']['attempts']] == ['failed', 'completed']
        assert all(call['audio_sha256'] == asr['inputs']['audio']['sha256'] for call in stack.calls if call['kind'] == 'transcription')
        with stack.database.connection() as db:
            requests = {row['id']: row['request'] for row in db.execute('SELECT id,request FROM node_runs WHERE owner_id=%s AND job_id=%s', (stack.owner,job['id'])).fetchall()}
        assert all(call['request_sha256'] == digest(requests[call['node_run_id']]) for call in stack.calls)
        manifest_response = client.get(path + '/manifest?download=true')
        assert manifest_response.status_code == 200
        manifest = manifest_response.json()
        assert manifest['layout'] == 'ticket_v1' and len(manifest['entries']) == 5
        checked = []
        for entry in manifest['entries']:
            if entry['node_id'] not in {'asr', 'translate'}:
                continue
            response = client.get(path + '/artifacts/' + entry['node_run_id'] + '/' + entry['output_port'] + '?download=true')
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == entry['storage']['sha256']
            assert '/'+job['id']+'/' in entry['storage']['storage_key']
            assert stack.runtime.store.read(stack.owner, entry['storage']) == response.content
            checked.append(entry['node_id'])
        assert sorted(checked) == ['asr', 'translate']
        # Fresh real worker process receives the same completed delivery, not new HTTP.
        stack.stop('model')
        with stack.factory.registered_factory() as broker:
            assert broker.publish(delivery)
        stack.start('model-restarted', 'app.operator', 'consume-registered-models')
        def drained():
            with stack.factory.registered_factory() as broker:
                result = broker.channel.queue_declare(queue=broker.config.queue('registered'), passive=True)
                return result.method.message_count == 0
        until(drained, bool)
        time.sleep(0.2)
        assert len(stack.calls) == 4
        assert client.get(path + '/manifest').content == manifest_response.content
        public = json.dumps({'job': done, 'manifest': manifest}, ensure_ascii=False, default=str)
        assert all(value not in public for value in [*stack.private['keys'].values(), *stack.private['rotated'].values()])
        (stack.evidence / 'installed-success.json').write_text(json.dumps({'ticket_id': job['id'], 'request_reference': ref,
            'calls': stack.calls, 'manifest_sha256': hashlib.sha256(manifest_response.content).hexdigest(),
            'manifest_entries': 5, 'downloaded_registered_nodes': checked, 'fresh_worker_duplicate_http_calls': 0}, ensure_ascii=False))
    finally:
        client.close()
        stack.stop('api')


def test_installed_worker_cancellation_stops_fallback_and_quarantines_late_result(installed):
    stack = installed
    client = stack.client_for_api(True)
    try:
        job, path = create_and_admit(stack, client, 'cancel')
        before = len(stack.calls)
        stack.request(client, 'POST', path + '/run')
        assert stack.entered.wait(12), 'Installed worker did not reach controlled HTTP'
        during = stack.request(client, 'GET', path)
        assert during['status'] == 'running'
        stack.request(client, 'POST', path + '/cancel', {'revision': during['revision']})
        stack.release.set()
        done = until(lambda: stack.request(client, 'GET', path), lambda value: value['status'] == 'cancelled' and any(run['status']=='quarantined' for run in value['runs']))
        assert [call['name'] for call in stack.calls[before:]] == ['cancel_first']
        assert not any(run['node_type']=='translate' for run in done['runs'])
        manifest = stack.request(client, 'GET', path + '/manifest')
        assert not any(entry['node_id'] in {'asr', 'translate'} for entry in manifest['entries'])
        with stack.database.connection() as db:
            late = db.execute('SELECT result FROM result_quarantine WHERE owner_id=%s AND job_id=%s', (stack.owner,job['id'])).fetchall()
        assert len(late) == 1 and late[0]['result']['outputs'] == {}
        assert stack.errors == []
        (stack.evidence / 'installed-cancel.json').write_text(json.dumps({'ticket_id': job['id'],
            'calls_after_cancel_barrier': stack.calls[before:], 'late_quarantine_rows': 1,
            'registered_manifest_entries': 0, 'following_candidate_requests': 0, 'downstream_translation_requests': 0}, ensure_ascii=False))
    finally:
        stack.release.set()
        client.close()
        stack.stop('api')


def test_installed_receiver_deadletters_forged_reference_without_retarget_or_http(installed):
    stack = installed
    saved = json.loads((stack.evidence/'installed-success.json').read_text())
    original = saved['request_reference']
    before_calls = len(stack.calls)
    with stack.database.connection() as db:
        before_receipts = db.execute('SELECT count(*) AS n FROM agent_deliveries').fetchone()['n']
    def dead_count():
        with stack.factory.registered_factory() as broker:
            return broker.channel.queue_declare(queue=broker.config.queue('registered')+'.dead', passive=True).method.message_count
    before_dead = dead_count()
    for changed in ({**original, 'request_sha256': 'f'*64}, {**original, 'attempt_id': uuid4().hex}):
        delivery = Delivery(canonical(changed), COMMAND, changed['attempt_id'], changed['job_id'])
        with stack.factory.registered_factory() as broker:
            assert broker.publish(delivery)
    until(dead_count, lambda value: value == before_dead+2)
    assert len(stack.calls) == before_calls
    with stack.database.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM agent_deliveries').fetchone()['n'] == before_receipts
    done = stack.runtime.get(stack.owner, saved['ticket_id'])
    assert done['status'] == 'completed'
    assert hashlib.sha256(stack.runtime.shared_manifest(stack.owner, saved['ticket_id'])).hexdigest() == saved['manifest_sha256']
    (stack.evidence/'installed-reference-fence.json').write_text(json.dumps({'forged_messages_deadlettered': 2,
        'extra_provider_requests': 0, 'extra_execution_receipts': 0, 'completed_manifest_unchanged': True}))
