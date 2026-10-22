"""Disposable PG/CAS + real loopback HTTP audio/DAG execution."""
import base64
import hashlib
import json
import os
import subprocess
import threading
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_foundation import admin as _admin
from test_foundation import db as _db
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime
from video_service.renewal_contracts import validate

admin, db = _admin, _db
SPEECH = Path(__file__).parent / 'fixtures' / 'synthetic-spoken.wav'


def audio_graph(asr, translation, fallback=()):
    nodes = [
        {'id': 'audio', 'type': 'extract_audio', 'options': {}, 'position': {'x': 180, 'y': 50}},
        {'id': 'prepare', 'type': 'preprocess_audio', 'options': {'vad_mode': 'off', 'audio_filter': 'off'}, 'position': {'x': 500, 'y': 50}},
        {'id': 'asr', 'type': 'transcribe', 'options': {}, 'position': {'x': 820, 'y': 50}, 'model_ref': asr, 'fallback_refs': list(fallback)},
        {'id': 'translate', 'type': 'translate', 'options': {}, 'position': {'x': 1140, 'y': 50}, 'model_ref': translation},
    ]
    links = [('$input', 'video', 'audio', 'video'), ('audio', 'audio', 'prepare', 'audio'), ('prepare', 'audio', 'asr', 'audio'), ('prepare', 'timeline', 'asr', 'timeline'), ('asr', 'transcript', 'translate', 'transcript')]
    return {'catalog_version': 1, 'revision': 0, 'name': '등록 API 전사와 번역', 'inputs': {'video': 'video'}, 'nodes': nodes, 'edges': [{'id': 'e' + str(i), 'source': {'node': a, 'port': b}, 'target': {'node': c, 'port': d}} for i, (a, b, c, d) in enumerate(links)]}


@pytest.fixture
def audio_wire():
    calls, entered, release = [], threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            if 'multipart/form-data' in self.headers.get('Content-Type', ''):
                message = BytesParser(policy=default).parsebytes(('Content-Type: ' + self.headers['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
                form = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True) for part in message.iter_parts()}
                audio = form['file']
                assert form['model'] == b'whisper-1' and form['response_format'] == b'verbose_json' and form['timestamp_granularities[]'] == b'segment'
                language = form.get('language', b'auto').decode()
                stage, body = 'transcription', {}
            else:
                body = json.loads(raw)
                part = body.get('contents', [{}])[0].get('parts', [{}])[0]
                stage = 'transcription' if 'inlineData' in part else 'translation'
                audio = base64.b64decode(part['inlineData']['data']) if stage == 'transcription' else b''
                language = body.get('systemInstruction', {}).get('parts', [{}])[0].get('text', '')
            assert (self.headers.get('x-goog-api-key') or self.headers.get('Authorization', '').removeprefix('Bearer ')) == 'synthetic-local-fixture-key'
            calls.append({'stage': stage, 'path': self.path, 'audio_sha256': hashlib.sha256(audio).hexdigest() if audio else None, 'audio_bytes': len(audio), 'language': language, 'body': body if stage == 'translation' else None})
            if '/cancel-' in self.path:
                entered.set()
                assert release.wait(12)
            code = 503 if '/fail-' in self.path else 200
            segments = [{'start': 0.1, 'end': 0.4, 'text': 'Controlled synthetic speech'}]
            if '/no-time-' in self.path:
                segments = [{'text': 'No timestamps'}]
            if stage == 'translation':
                texts = json.loads(body['contents'][0]['parts'][0]['text'])
                assert texts == ['Controlled synthetic speech']
                text = json.dumps(['통제된 번역'])
            else:
                text = json.dumps(segments)
            value = {'segments': segments} if 'multipart/form-data' in self.headers.get('Content-Type', '') else {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text, 'thoughtSignature': 'c2ln'}]}}]}
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
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


def register_models(database, owner, credentials, origin, mode='success'):
    registry, result = Registry(database), []
    for name, protocol, model, speech in [('fail-gemini' if mode == 'success' else mode + '-gemini', 'gemini', 'gemini-fixture', True), ('fail-openai' if mode == 'fail' else 'ok-openai', 'openai', 'whisper-1', True), ('translation', 'gemini', 'gemini-fixture', False)]:
        cid, mid = uuid4().hex, uuid4().hex
        registry.save_connection(owner, cid, revision=0, name=name, provider=protocol, protocol=protocol, endpoint=origin + '/' + name + '/v1')
        credentials.save(owner, cid, revision=1, secret='synthetic-local-fixture-key')
        registry.save_model(owner, mid, revision=0, name=name, model=model, connection_id=cid, connection_revision=2, model_types=['speech_recognition' if speech else 'text'], input_modalities=['audio' if speech else 'text'], output_modalities=['text'], capabilities=['speech_recognition' if speech else 'text_generation'])
        result.append({'model_id': mid, 'revision': 1})
    return result


def movie_from_speech(root):
    movie = Path(root) / 'spoken.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=5:d=10', '-i', str(SPEECH), '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(movie)], check=True, capture_output=True, timeout=30)
    return movie.read_bytes()


@pytest.mark.parametrize('mode', ['success', 'ok'])
def test_verified_source_audio_to_registered_asr_to_translation(db, admin, audio_wire, tmp_path, mode):
    owner = admin[0]['id']
    origin, calls, _, _ = audio_wire
    credentials = CredentialStore(db, os.urandom(32))
    refs = register_models(db, owner, credentials, origin, mode)
    graph = audio_graph(refs[0], refs[2], refs[1:2] if mode == 'success' else [])
    assert validate(graph)['valid'], validate(graph)
    translator = TranslationRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    runtime = Execution(db, ContentStore(tmp_path), translation_runtime=translator)
    runtime.transcription_runtime = TranscriptionRuntime(credentials, transport_factory=lambda: httpx.HTTPTransport(retries=0), approved_origins={origin}, mode='controlled_http')
    saved = runtime.save_definition(owner, uuid4().hex, graph)
    assert runtime.inspect(owner, saved['id'], saved['revision'])['supported']
    source = runtime.ingest(owner, 'spoken.mp4', movie_from_speech(tmp_path))
    job = runtime.create(owner, source['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex, options={'source_language': 'en', 'target_language': 'ko'})
    if mode == 'success':
        for ref in refs[:2]:
            pinned = credentials.model(owner, ref['model_id'], 1)
            Registry(db).save_model(owner, ref['model_id'], revision=1, name='Later head', model='changed-after-ticket', connection_id=pinned['connection_id'], connection_revision=2, model_types=['speech_recognition'], input_modalities=['audio'], output_modalities=['text'], capabilities=['speech_recognition'])
            credentials.save(owner, pinned['connection_id'], revision=2, secret='synthetic-later-key-not-ticket')
    plan = runtime.plan(owner, job['id'])
    assert plan['ready'], plan['reasons']
    consent = runtime.confirm(owner, job['id'], plan['token'], uuid4().hex)
    runtime.admit(owner, job['id'], consent['id'], uuid4().hex)
    done = runtime.run_local(owner, job['id'])
    assert done['status'] == 'completed', [(r['node_type'],r['status']) for r in done['runs']]
    asr = next(r for r in done['runs'] if r['node_type'] == 'transcribe')
    translation = next(r for r in done['runs'] if r['node_type'] == 'translate')
    assert [a['status'] for a in asr['result']['transcription']['attempts']] == (['failed', 'completed'] if mode == 'success' else ['completed'])
    assert translation['inputs']['transcript'] == asr['result']['outputs']['transcript']
    output = json.loads(runtime.store.read(owner, translation['result']['outputs']['transcript']))
    assert output == [{'start': 0.1, 'end': 0.4, 'text': '통제된 번역'}]
    assert [c['stage'] for c in calls] == (['transcription', 'transcription', 'translation'] if mode == 'success' else ['transcription', 'translation'])
    assert all(c['audio_sha256'] == asr['inputs']['audio']['sha256'] for c in calls if c['stage'] == 'transcription')
    export_outcome(done, calls, mode)


def export_outcome(done, calls, name):
    if not os.environ.get('MIDEAGENT_ASR_EVIDENCE'):
        return
    directory = Path(os.environ['MIDEAGENT_ASR_EVIDENCE'])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ('asr-' + name + '.json')).write_text(json.dumps({
        'boundary': 'actual disposable PG/CAS + offline synthesized speech + controlled loopback HTTP, not recognition accuracy',
        'job_id': done['id'], 'status': done['status'], 'snapshot_sha256': done['snapshot_sha256'],
        'model_refs': [{k:n[k] for k in ('id','type','model_ref','fallback_refs') if k in n} for n in done['snapshot']['definition']['nodes']],
        'options': done['snapshot']['options'],
        'runs': [{k:r[k] for k in ('node_type','status','inputs','result','transcription') if k in r} for r in done['runs']],
        'calls': calls,
    }, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('mode', ['fail', 'no-time', 'cancel'])
def test_transcription_exhaustion_missing_timing_and_cancel_never_start_translation(db, admin, audio_wire, tmp_path, mode):
    from concurrent.futures import ThreadPoolExecutor

    origin, calls, entered, release = audio_wire
    owner = admin[0]['id']
    credentials = CredentialStore(db, os.urandom(32))
    refs = register_models(db, owner, credentials, origin, mode)
    fallback = refs[1:2] if mode != 'no-time' else []
    kwargs = {'transport_factory': lambda: httpx.HTTPTransport(retries=0), 'approved_origins': {origin}, 'mode': 'controlled_http'}
    runtime = Execution(db, ContentStore(tmp_path), translation_runtime=TranslationRuntime(credentials, **kwargs), transcription_runtime=TranscriptionRuntime(credentials, **kwargs))
    graph = runtime.save_definition(owner, uuid4().hex, audio_graph(refs[0], refs[2], fallback))
    source = runtime.ingest(owner, 'spoken.mp4', movie_from_speech(tmp_path))
    job = runtime.create(owner, source['asset_id'], graph['id'], graph['revision'], request_id=uuid4().hex, options={'source_language':'en','target_language':'ko'})
    plan = runtime.plan(owner, job['id'])
    assert plan['ready'], plan['reasons']
    consent = runtime.confirm(owner, job['id'], plan['token'], uuid4().hex)
    runtime.admit(owner, job['id'], consent['id'], uuid4().hex)
    if mode == 'cancel':
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(runtime.run_local, owner, job['id'])
            assert entered.wait(8)
            current = runtime.get(owner, job['id'])
            runtime.cancel(owner, job['id'], current['revision'])
            release.set()
            done = future.result(8)
        assert done['status'] == 'cancelled'
        assert len(calls) == 1
        assert not any(r['node_type'] == 'translate' for r in done['runs'])
    else:
        done = runtime.run_local(owner, job['id'])
        assert done['status'] == 'failed'
        assert len(calls) == (2 if mode == 'fail' else 1)
    asr = next(r for r in done['runs'] if r['node_type'] == 'transcribe')
    assert asr['transcription']['selected'] is None
    assert not (asr['result'] or {}).get('outputs')
    assert all(call['stage'] == 'transcription' for call in calls)
    if mode == 'no-time':
        assert asr['transcription']['attempts'][0]['error'] == 'invalid_response'
    export_outcome(done, calls, mode)
