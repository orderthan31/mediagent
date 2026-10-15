"""Actual isolated ASGI + durable review tickets; explicit deterministic executor.
No GPU/provider/user media. Each HTTP call reloads disk in a fresh process.
"""
import sys, json, fcntl, subprocess, hashlib
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import settings_routes
from video_service.workflow_definitions import DefinitionStore
from video_service.llm_settings import LLMSettingsStore, MODEL_FIELDS, PROVIDER_FIELDS, FLAGS
from video_service.review_tickets import ReviewTicketStore
from video_service.review import BLOCKED_TEXT
from video_service.subtitles import segments_to_srt
from video_service.transcript import TranscriptSegment
sys.path.insert(0, '/src/tests')
from test_workflow_decision import decision_graph
r = json.load(sys.stdin)
root = Path('/fixture')
settings_routes.settings = SimpleNamespace(storage_root=root, service_quota_bytes=10**9, min_free_space_bytes=0)
with (root / '.seed.lock').open('a+') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if not (root / 'seeded.json').exists():
        directory = root / '.assets' / ('b'*32)
        directory.mkdir(parents=True)
        source = directory / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-shortest', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
        (directory / 'asset.json').write_text(json.dumps({'asset_id': 'b'*32, 'owner_id': None, 'source_filename': 'source.mp4', 'original_filename': '안전 합성 판단 입력.mp4', 'size_bytes': source.stat().st_size, 'created_at': '2026-01-01T00:00:00Z'}))
        definition = decision_graph()
        definition.pop('id')
        definition['revision'] = 0
        DefinitionStore(root).save('a'*32, definition)
        (root / 'seeded.json').write_text('{}')
app = FastAPI()
app.state.auth = SimpleNamespace(store=None)
app.state.cors_origins = ['http://testserver']
app.include_router(settings_routes.router)
app.state.decision_executor_label = '격리 결정론 검수 executor · 실모델/미디어 엔진 아님'
def event(value):
    with (root / 'actual-trace.jsonl').open('a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(value, ensure_ascii=False) + '\n')
class ControlledProvider:
    descriptor = {'id': 'offline-controlled-fixture', 'revision': '1', 'schema_version': 1, 'paid': False}
    def decide(self, context):
        scenario = json.loads((root/'scenario.json').read_text()) if (root/'scenario.json').exists() else {}
        event({'mode': 'explicit_structured_adapter_fixture_NOT_external_inference', 'decision_input': context['input']})
        if scenario.get('adapter_error'):
            raise RuntimeError('Controlled offline adapter failure')
        return {'version': 1, 'label': scenario.get('label', 'pass'), 'confidence': .9, 'reason': '격리 고정 adapter의 구조화 fixture 결과 · 외부 모델 추론 아님'}
app.state.decision_adapter_descriptor = ControlledProvider.descriptor
def factory(preferences, options, admitted):
    def execute(step, inputs, work, check):
        event({'node': step['id'], 'phase_serving_revision': preferences['revision'], 'mode': 'explicit_deterministic_fixture'})
        outputs = {}
        for port in step['outputs']:
            output = work / (port + ('.srt' if port == 'subtitles' else '.fixture'))
            if step['type'] == 'transcribe':
                output.write_text(json.dumps([{'start': 0, 'end': .2, 'text': BLOCKED_TEXT}], ensure_ascii=False))
            elif step['type'] == 'generate_subtitle':
                cues = json.loads(inputs['transcript'].read_text())
                event({'received_by_subtitle': cues, 'sha256': hashlib.sha256(inputs['transcript'].read_bytes()).hexdigest()})
                output.write_text(segments_to_srt([TranscriptSegment.from_dict(c) for c in cues]))
            elif step['type'] == 'encode' and 'subtitles' in inputs:
                output.write_text(json.dumps({'mode': 'explicit_deterministic_fixture_NOT_video', 'subtitle_sha256': hashlib.sha256(inputs['subtitles'].read_bytes()).hexdigest(), 'subtitles': inputs['subtitles'].read_text()}, ensure_ascii=False))
            else:
                output.write_text(json.dumps({'mode': 'explicit_deterministic_fixture', 'node': step['id'], 'fixture_metadata': {'reviewable': True}}))
            outputs[port] = output
        return outputs
    execute.decision_provider = ControlledProvider()
    execute.review_duration = .4
    return execute
app.state.decision_executor_factory = factory
@app.get('/api/videos')
def videos():
    return {'videos': [json.loads((root / '.assets' / ('b'*32) / 'asset.json').read_text())]}
with TestClient(app) as client:
    if r.get('drift'):
        store = LLMSettingsStore(root)
        old = store.public()
        values = {k: old[k] for k in (*MODEL_FIELDS, *PROVIDER_FIELDS, *FLAGS, 'revision')}
        values['translation_model'] = 'gemini-isolated-decision-next'
        store.update(None, values)
    if r.get('external_edit'):
        identity = r['path'].split('/')[4]
        doc = ReviewTicketStore(root).review_document(identity, 'review_text')
        view = doc.get()
        doc.save(view['state_revision'], view['revision'], view['sha256'], view['target'], [{'start': 0, 'end': .2, 'text': '외부 명시 수정본'}])
    response = client.request(r['method'], r['path'], json=r.get('payload'))
    if '/artifacts/' in r['path'] or r['path'].endswith('/input'):
        import base64
        print(json.dumps({'status': response.status_code, 'binary': base64.b64encode(response.content).decode(), 'content_type': response.headers.get('content-type')}))
    else:
        print(json.dumps({'status': response.status_code, 'body': response.json()}, ensure_ascii=False))
