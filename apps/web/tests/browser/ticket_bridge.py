"""Safe browser bridge to actual ticket API/storage with an explicit deterministic executor."""
import sys,json,time,fcntl,subprocess
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import settings_routes
from video_service.workflow_definitions import DefinitionStore
from video_service.llm_settings import LLMSettingsStore,MODEL_FIELDS,PROVIDER_FIELDS,FLAGS
from video_service.workflow_tickets import public_preferences
sys.path.insert(0,'/src/tests')
from test_sequential_workflow import graph
r=json.load(sys.stdin);root=Path('/fixture');settings_routes.settings=SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)
with (root/'.fixture-seed.lock').open('a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if not (root/'seeded.json').exists():
        a=root/'.assets'/('b'*32);a.mkdir(parents=True);video=a/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-f','lavfi','-i','sine=frequency=440:duration=0.4','-shortest','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True)
        asset={'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'안전 합성 입력.mp4','size_bytes':video.stat().st_size,'created_at':'2026-01-01T00:00:00Z'}
        (a/'asset.json').write_text(json.dumps(asset));d=graph();d['name']='격리 순차 정의';d['revision']=0;d['nodes'][1]['options']['audio_filter']='off';DefinitionStore(root).save('a'*32,d)
        d['name']='미지원 분리 사슬';d['nodes'].append({'id':'other','type':'analyze','position':{'x':0,'y':0},'options':{}});d['edges'].append({'id':'c','source':{'node':'$input','port':'video'},'target':{'node':'other','port':'video'}});DefinitionStore(root).save('c'*32,d)
        (root/'seeded.json').write_text('{}')
app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
app.state.workflow_executor_label='격리 결정론 executor · 실제 모델 아님'
def factory(preferences,options):
    def execute(step,inputs,work,check):
        time.sleep(.2);check()
        if r.get('fail_run') and step['id']=='prepare':
            (work/'partial-result.json').write_text('{"incomplete":true,"engine":"deterministic fixture"}')
            raise RuntimeError('Injected deterministic node failure')
        result={}
        for port in step['outputs']:
            p=work/(port+'.fixture');p.write_text(json.dumps({'engine':'deterministic fixture','node':step['id'],'options':step['options'],'settings':public_preferences(preferences),'ticket_options':options}));result[port]=p
        return result
    return execute
app.state.workflow_executor_factory=factory
@app.get('/api/videos')
def videos():return {'videos':[json.loads((root/'.assets'/('b'*32)/'asset.json').read_text())]}
with TestClient(app) as client:
    if r.get('drift'):
        store=LLMSettingsStore(root);p=store.public();values={k:p[k] for k in (*MODEL_FIELDS,*PROVIDER_FIELDS,*FLAGS,'revision')};values['translation_model']='gemini-fixture-next';store.update(None,values)
    if r.get('edit_definition'):
        s=DefinitionStore(root);d=s.get('a'*32);p={k:d[k] for k in ('catalog_version','revision','name','inputs','nodes','edges')};p['name']='새로 편집한 정의';p['nodes'][1]['options']['audio_filter']='strong';s.save('a'*32,p)
    response=client.request(r['method'],r['path'],json=r.get('payload'))
    if '/artifacts/' in r['path']:
        import base64
        print(json.dumps({'status':response.status_code,'binary':base64.b64encode(response.content).decode()}))
    else:print(json.dumps({'status':response.status_code,'body':response.json()},ensure_ascii=False))
