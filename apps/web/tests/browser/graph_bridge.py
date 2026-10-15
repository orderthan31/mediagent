"""Isolated actual ASGI graph tickets + explicit deterministic, synchronized executor."""
import sys, json, time, fcntl, subprocess, threading
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import settings_routes
from video_service.workflow_definitions import DefinitionStore
from video_service.llm_settings import LLMSettingsStore, MODEL_FIELDS, PROVIDER_FIELDS, FLAGS
from video_service.workflow_tickets import public_preferences
sys.path.insert(0, '/src/tests')
from test_parallel_workflow import branching_graph
from test_sequential_workflow import graph
r = json.load(sys.stdin)
root = Path('/fixture')
settings_routes.settings = SimpleNamespace(storage_root=root, service_quota_bytes=10**9, min_free_space_bytes=0)
with (root / '.seed.lock').open('a+') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if not (root / 'seeded.json').exists():
        a = root / '.assets' / ('b' * 32)
        a.mkdir(parents=True)
        video = a / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-shortest', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(video)], check=True)
        (a / 'asset.json').write_text(json.dumps({'asset_id': 'b'*32, 'owner_id': None, 'source_filename': 'source.mp4', 'original_filename': '안전 합성 입력.mp4', 'size_bytes': video.stat().st_size, 'created_at': '2026-01-01T00:00:00Z'}))
        d = branching_graph()
        d['name'] = '격리 수동 병렬·목록 합류'
        d['revision'] = 0
        DefinitionStore(root).save('a'*32, d)
        d = graph()
        d['revision'] = 0
        d['name'] = '미지원 GPU VAD'
        d['nodes'][1]['options']['vad_mode'] = 'nvidia'
        DefinitionStore(root).save('c'*32, d)
        (root / 'seeded.json').write_text('{}')
app = FastAPI()
app.state.auth = SimpleNamespace(store=None)
app.state.cors_origins = ['http://testserver']
app.include_router(settings_routes.router)
app.state.graph_executor_label = '격리 결정론 병렬 executor · 실제 모델 아님'
trace, trace_lock = [], threading.Lock()
pair = threading.Barrier(2)
failed = threading.Event()
def event(identity, kind):
    with trace_lock:
        trace.append({'node': identity, 'event': kind, 'time_ns': time.monotonic_ns(), 'thread': threading.get_ident()})
def factory(preferences, options):
    def execute(step, inputs, work, check):
        event(step['id'], 'start')
        if options.get('branch_choices', {}).get('choose', 'both') == 'both':
            pair.wait(timeout=5)
        try:
            check()
            if r.get('hold_run'):
                released = root / ('release-' + r['path'].split('/')[-2])
                deadline = time.monotonic() + 20
                while not released.exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError('Fixture progress observer did not release both running nodes')
                    time.sleep(.02)
            if r.get('fail_run') and step['id'] == 'a':
                (work / 'partial-result.json').write_text('{"engine":"deterministic fixture","partial":true}')
                failed.set()
                raise RuntimeError('Injected deterministic branch failure')
            if r.get('fail_run') and step['id'] == 'b':
                if not failed.wait(timeout=5):
                    raise RuntimeError('The other branch did not reach its controlled failure')
            path = work / 'same.fixture'
            path.write_text(json.dumps({'engine': 'deterministic fixture', 'node': step['id'], 'options': step['options'], 'settings': public_preferences(preferences)}))
            event(step['id'], 'succeeded')
            return {'video': path}
        except Exception:
            event(step['id'], 'failed')
            raise
    return execute
app.state.graph_executor_factory = factory
@app.get('/api/videos')
def videos():
    return {'videos': [json.loads((root / '.assets' / ('b'*32) / 'asset.json').read_text())]}
@app.post('/api/settings/graph-fixture/release')
def release(payload: dict):
    import re
    identity = payload.get('id', '')
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('Invalid isolated ticket ID')
    (root / ('release-' + identity)).write_text('released')
    return {'released': True}
with TestClient(app) as client:
    if r.get('drift'):
        s = LLMSettingsStore(root)
        old = s.public()
        values = {k: old[k] for k in (*MODEL_FIELDS, *PROVIDER_FIELDS, *FLAGS, 'revision')}
        values['translation_model'] = 'gemini-fixture-next'
        s.update(None, values)
    if r.get('edit_definition'):
        s = DefinitionStore(root)
        d = s.get('a'*32)
        p = {k: d[k] for k in ('catalog_version', 'revision', 'name', 'inputs', 'nodes', 'edges')}
        p['name'] = '외부 편집된 병렬 정의'
        p['nodes'][1]['options']['quality_profile'] = 'high'
        s.save('a'*32, p)
    response = client.request(r['method'], r['path'], json=r.get('payload'))
    if trace:
        folder = root / 'execution-traces'
        folder.mkdir(exist_ok=True)
        (folder / (r['path'].split('/')[-2] + '.json')).write_text(json.dumps(trace))
    if '/artifacts/' in r['path']:
        import base64
        print(json.dumps({'status': response.status_code, 'binary': base64.b64encode(response.content).decode()}))
    else:
        print(json.dumps({'status': response.status_code, 'body': response.json()}, ensure_ascii=False))
