"""WF08 browser bridge: actual ASGI/ledger, synthetic media, controlled adapter only."""
import sys,json,fcntl,subprocess,base64,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,'/src/tests')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import settings_routes,routes,asset_routes,workflow_routes,execution_approval_routes
from video_service.workflow_definitions import DefinitionStore
from video_service.model_registry import ModelRegistry
from video_service.repository import FilesystemJobRepository
from media_agent.registered_nodes import RegisteredDecisionProvider
from test_workflow_decision import decision_graph

r=json.load(sys.stdin);root=Path('/fixture')
config=SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0,storage_audit_interval_seconds=300)
for module in (settings_routes,routes,asset_routes,workflow_routes):module.settings=config
routes.repository=FilesystemJobRepository(root)
with (root/'.seed.lock').open('a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if not (root/'seeded').exists():
        directory=root/'.assets'/('b'*32);directory.mkdir(parents=True);source=directory/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
        (directory/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'WF08 안전 합성 영상.mp4','size_bytes':source.stat().st_size,'status':'ready','created_at':'2026-01-01T00:00:00Z'}))
        ModelRegistry(root).save('c'*32,{'revision':0,'name':'WF08 통제 판단 모델','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
        graph=decision_graph();graph.pop('id');graph['revision']=0;graph['name']='WF08 서버 실행 승인 검사';graph['nodes'][0]['model_ref']={'model_id':'c'*32,'revision':1}
        DefinitionStore(root).save('a'*32,graph)
        (root/'clock.json').write_text(json.dumps({'now':time.time()}));(root/'seeded').write_text('fixture only')
    if r.get('advance_clock'):
        clock=json.loads((root/'clock.json').read_text());clock['now']+=r['advance_clock'];(root/'clock.json').write_text(json.dumps(clock))
clock=json.loads((root/'clock.json').read_text())['now']
def trace(event):
    with (root/'actual-trace.jsonl').open('a') as f:fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(event)+'\n')
def factory(bound,options,admitted,bindings):
    def execute(step,inputs,work,check):
        trace({'node':step['id'],'kind':'controlled native fixture, NOT inference'})
        result={}
        for port,kind in step['outputs'].items():
            p=work/(port+'.fixture');p.write_text(json.dumps({'controlled':True,'type':kind}));result[port]=p
        return result
    def transport(*args):
        trace({'node':'judge','kind':'controlled transport response, NO provider/network'})
        return {'version':1,'label':'pass','confidence':.9,'reason':'controlled fixture; NOT live inference'}
    execute.decision_provider=RegisteredDecisionProvider(bound,paid_allowed=True,transport=transport) if bound.get('decision_model') else None
    return execute
app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.state.work_executor_factory=factory
for router in (settings_routes.router,routes.router,asset_routes.router,workflow_routes.router,execution_approval_routes.router):app.include_router(router)
with patch('video_service.execution_authorization.time.time',lambda:clock):
    manager=patch.object(execution_approval_routes,'classify',lambda roles:{'state':'unknown','amount':None,'notice':'통제된 비용 분류 오류 · 실행 차단'}) if r.get('cost_error') else patch.object(app.state,'fixture_label','NO LIVE PROVIDER',create=True)
    with manager,TestClient(app) as client:
        response=client.request(r['method'],r['path'],json=r.get('payload'),headers=r.get('headers',{}))
        if '/artifacts/' in r['path'] or r['path'].endswith('/input'):
            print(json.dumps({'status':response.status_code,'binary':base64.b64encode(response.content).decode(),'content_type':response.headers.get('content-type')}))
        else:print(json.dumps({'status':response.status_code,'body':response.json()},ensure_ascii=False))
