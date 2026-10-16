"""WF07 isolated real ASGI/store; controlled failure and synthetic CPU media only."""
import sys,json,fcntl,subprocess,hashlib,base64
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import settings_routes
from video_service.workflow_definitions import DefinitionStore

r=json.load(sys.stdin);root=Path('/fixture')
settings_routes.settings=SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)
with (root/'.seed.lock').open('a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if not (root/'seeded.json').exists():
        directory=root/'.assets'/('b'*32);directory.mkdir(parents=True)
        source=directory/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
        (directory/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'WF07 안전 합성 영상.mp4','size_bytes':source.stat().st_size,'created_at':'2026-01-01T00:00:00Z'}))
        specs=[('a','encode',{'subtitle_mode':'none'}),('b','encode',{'subtitle_mode':'none'}),('joined','join',{'left_type':'video','right_type':'video'}),('failure','analyze',{})]
        links=[('$input','video','a','video'),('$input','video','b','video'),('a','video','joined','left'),('b','video','joined','right'),('$input','video','failure','video')]
        graph={'catalog_version':1,'revision':0,'name':'복구 검사 흐름','inputs':{'video':'video'},'nodes':[{'id':n,'type':t,'options':o,'position':{'x':i*200,'y':0}} for i,(n,t,o) in enumerate(specs)],'edges':[{'id':'e'+str(i),'source':{'node':a,'port':p},'target':{'node':b,'port':q}} for i,(a,p,b,q) in enumerate(links)]}
        DefinitionStore(root).save('a'*32,graph)
        graph['revision']=1;graph['name']='복구 검사 흐름 최신';DefinitionStore(root).save('a'*32,graph)
        (root/'seeded.json').write_text('{}')
app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
def event(value):
    with (root/'actual-trace.jsonl').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(value)+'\n')
def factory(*args):
    def execute(step,inputs,work,check):
        event({'node':step['id'],'mode':'synthetic CPU or controlled failure; NO external inference'})
        if step['id']=='failure' and not (root/'failed-once').exists():
            (root/'failed-once').write_text('controlled failure already injected')
            (work/'partial-metadata.json').write_text('{"controlled_partial":true}')
            raise RuntimeError('explicit isolated failure, not a provider failure')
        if step['type']=='encode':
            output=work/'output.mp4'
            subprocess.run(['ffmpeg','-v','error','-i',str(inputs['video']),'-c:v','libx264','-threads','1',str(output)],check=True)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
            event({'encoded':step['id'],'duration':probe['format']['duration'],'sha256':hashlib.sha256(output.read_bytes()).hexdigest()})
            return {'video':output}
        output=work/'metadata.json';output.write_bytes(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(inputs['video'])]));return {'metadata':output}
    return execute
app.state.work_executor_factory=factory
app.state.work_executor_label='격리 실제 CPU·통제 실패 / 실provider 아님'
@app.get('/api/videos')
def videos():return {'videos':[json.loads((root/'.assets'/('b'*32)/'asset.json').read_text())]}
if r.get('seed_interrupted'):
    from video_service.recovery_tickets import RecoveryTicketStore
    from video_service.llm_settings import LLMSettingsStore
    with (root/'.interrupt-seed.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not (root/'interrupted-ticket.json').exists():
            current=DefinitionStore(root).get('a'*32)
            graph={k:current[k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
            graph.update(revision=0,name='중단 복구 확인')
            definition=DefinitionStore(root).save('d'*32,graph)
            asset=json.loads((root/'.assets'/('b'*32)/'asset.json').read_text())
            source=root/'.assets'/('b'*32)/'source.mp4'
            asset={k:asset[k] for k in ('asset_id','original_filename','size_bytes')}
            asset['source_mtime_ns']=source.stat().st_mtime_ns
            store=RecoveryTicketStore(root)
            ticket=store.create('controlled-interrupted',{'definition_id':definition['id'],'definition_revision':definition['revision'],'asset_id':asset['asset_id'],'options':{}},lambda:definition,lambda:asset)
            prefs=LLMSettingsStore(root).resolve(None)
            plan=store.plan(ticket['id'],prefs);confirmed=store.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            def interrupted_factory(*args):
                def interrupted(step,*args):
                    event({'interruption_node':step['id'],'mode':'controlled interruption before any real engine/provider'})
                    raise SystemExit('controlled coordinator interruption')
                return interrupted
            try:
                store.run(ticket['id'],prefs,source,interrupted_factory,request_id='controlled-crash',revision=confirmed['revision'],token=plan['token'],operation='start')
            except SystemExit:pass
            (root/'interrupted-ticket.json').write_text(json.dumps({'id':ticket['id']}))
with TestClient(app) as client:
    response=client.request(r['method'],r['path'],json=r.get('payload'))
    if '/artifacts/' in r['path'] or r['path'].endswith('/input'):
        print(json.dumps({'status':response.status_code,'binary':base64.b64encode(response.content).decode(),'content_type':response.headers.get('content-type')}))
    else:print(json.dumps({'status':response.status_code,'body':response.json()},ensure_ascii=False))
