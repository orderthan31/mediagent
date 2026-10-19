import copy
import importlib.util
import unittest


def graph():
    return {'catalog_version':1,'revision':1,'name':'순차 검증','inputs':{'video':'video'},'nodes':[
        {'id':'extract','type':'extract_audio','position':{'x':100,'y':100},'options':{}},
        {'id':'prepare','type':'preprocess_audio','position':{'x':400,'y':100},'options':{'audio_filter':'strong','vad_mode':'off'}}],
        'edges':[{'id':'a','source':{'node':'$input','port':'video'},'target':{'node':'extract','port':'video'}},
                 {'id':'b','source':{'node':'extract','port':'audio'},'target':{'node':'prepare','port':'audio'}}]}


class SequentialTests(unittest.TestCase):
    def test_compiler_uses_definition_ports_options_and_rejects_nonsequential(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.sequential_workflow'),'Definition-driven sequential compiler missing')
        from video_service.sequential_workflow import compile_sequence
        d=graph();p=compile_sequence(d)
        self.assertTrue(p['supported']);self.assertEqual([n['id'] for n in p['steps']],['extract','prepare'])
        self.assertEqual(p['steps'][1]['options']['audio_filter'],'strong')
        self.assertEqual(p['steps'][1]['bindings']['audio'],{'node':'extract','port':'audio'})
        branch=copy.deepcopy(d);branch['nodes'].append({'id':'other','type':'analyze','position':{'x':0,'y':0},'options':{}})
        branch['edges'].append({'id':'c','source':{'node':'$input','port':'video'},'target':{'node':'other','port':'video'}})
        self.assertFalse(compile_sequence(branch)['supported'])
        d['edges'][1]['source']['port']='video'
        self.assertFalse(compile_sequence(d)['supported'])

    def test_real_persistence_bound_plan_and_first_failure(self):
        import tempfile
        from pathlib import Path
        self.assertIsNotNone(importlib.util.find_spec('video_service.workflow_tickets'),'Ticket orchestration missing')
        from video_service.workflow_tickets import TicketStore, TicketConflict
        from video_service.llm_settings import LLMSettingsStore
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'synthetic.bin';source.write_bytes(b'safe synthetic input')
            d=graph();d['id']='a'*32
            asset={'asset_id':'b'*32,'original_filename':'synthetic.bin','size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
            prefs=LLMSettingsStore(root).resolve();prefs['api_keys']['gemini']='WF03_FAKE_NOT_A_REAL_KEY'
            store=TicketStore(root);identity={'definition_id':d['id'],'definition_revision':1,'asset_id':asset['asset_id'],'options':{'source_language':'auto','target_language':'ko','video_description':''}}
            ticket=store.create('request-one',identity,lambda:d,lambda:asset)
            self.assertEqual(ticket['status'],'held')
            self.assertEqual(store.create('request-one',identity,lambda:None,lambda:None)['id'],ticket['id'])
            d['nodes'][1]['options']['audio_filter']='off'
            self.assertEqual(store.get(ticket['id'])['definition']['nodes'][1]['options']['audio_filter'],'strong')
            preview=store.plan(ticket['id'],prefs)
            ticket=store.confirm(ticket['id'],ticket['revision'],preview['token'],False,prefs)
            drift={**prefs,'revision':prefs['revision']+1}
            with self.assertRaises(TicketConflict):store.run(ticket['id'],drift,source,lambda p,o:None)
            self.assertEqual(store.get(ticket['id'])['status'],'confirmed')
            seen=[]
            def factory(bound,options):
                self.assertEqual(bound['transcription_model'],prefs['transcription_model'])
                def execute(step,inputs,work,check):
                    seen.append(step['id'])
                    if step['id']=='prepare':
                        (work/'partial-audio.json').write_text('{"partial":true}')
                        raise RuntimeError('safe injected failure')
                    result={}
                    for port in step['outputs']:
                        p=work/(port+'.fixture');p.write_bytes(b'deterministic output');result[port]=p
                    return result
                return execute
            result=store.run(ticket['id'],prefs,source,factory)
            self.assertEqual(result['status'],'failed');self.assertEqual(seen,['extract','prepare'])
            self.assertEqual(result['steps'][0]['status'],'succeeded');self.assertEqual(result['steps'][1]['status'],'failed')
            self.assertTrue(result['steps'][1]['partial_artifacts'])
            self.assertNotIn('WF03_FAKE',str(store.get(ticket['id'])))
            with self.assertRaises(TicketConflict):store.run(ticket['id'],prefs,source,factory)

    def test_stored_sequence_cannot_diverge_from_frozen_definition(self):
        import tempfile,json
        from pathlib import Path
        from video_service.workflow_tickets import TicketStore,TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            store=TicketStore(Path(directory));d=graph();d['id']='a'*32
            identity={'definition_id':d['id'],'definition_revision':1,'asset_id':'b'*32,'options':{}}
            t=store.create('request',identity,lambda:d,lambda:{'asset_id':'b'*32})
            t['sequence']['steps'][0]['type']='encode'
            (store.directory_for(t['id'])/'ticket.json').write_text(json.dumps(t))
            with self.assertRaises(TicketConflict):store.plan(t['id'],{'revision':0,'api_keys':{}})

    def test_real_node_adapter_with_isolated_synthetic_cpu_media(self):
        import tempfile,subprocess,json
        from pathlib import Path
        self.assertIsNotNone(importlib.util.find_spec('media_agent.sequential_nodes'),'Real node adapter missing')
        from media_agent.sequential_nodes import MediaNodeExecutor
        from video_service.workflow_tickets import TicketStore
        from video_service.llm_settings import LLMSettingsStore
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'synthetic.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-f','lavfi','-i','sine=frequency=440:duration=0.4','-shortest','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            d=graph();d['id']='a'*32;d['nodes'][1]['options']['audio_filter']='off'
            asset={'asset_id':'b'*32,'original_filename':'synthetic.mp4','size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
            s=TicketStore(root);p=LLMSettingsStore(root).resolve();t=s.create('cpu',{'definition_id':d['id'],'definition_revision':1,'asset_id':asset['asset_id'],'options':{'source_language':'auto','target_language':'ko','video_description':''}},lambda:d,lambda:asset)
            plan=s.plan(t['id'],p);t=s.confirm(t['id'],1,plan['token'],False,p)
            out=s.run(t['id'],p,source,lambda prefs,options:MediaNodeExecutor(prefs,options))
            self.assertEqual(out['status'],'completed',out.get('error'))
            self.assertTrue(s.artifact_path(t['id'],'extract','audio').is_file())
            spans=json.loads(s.artifact_path(t['id'],'prepare','timeline').read_text())
            self.assertTrue(spans)
            from video_service.transcript import TranscriptSegment
            class FixtureProvider:
                transcription_identity='fixture:no-network'
                def transcribe(self,audio,language,check,**kwargs):return [TranscriptSegment(0,0.15,'안전 테스트')]
                def translate(self,segments,language,check,**kwargs):return [TranscriptSegment(x.start,x.end,'격리 번역') for x in segments]
            full=graph();full['id']='c'*32;full['nodes'][1]['options']['audio_filter']='off'
            for identity,kind in [('stt','transcribe'),('translate','translate'),('srt','generate_subtitle'),('encode','encode'),('validate','validate_video')]:
                full['nodes'].append({'id':identity,'type':kind,'position':{'x':0,'y':0},'options':{'video_codec':'h264','subtitle_mode':'burn'} if kind=='encode' else {}})
            for i,(a,ap,b,bp) in enumerate([('prepare','audio','stt','audio'),('prepare','timeline','stt','timeline'),('stt','transcript','translate','transcript'),('translate','transcript','srt','transcript'),('$input','video','encode','video'),('srt','subtitles','encode','subtitles'),('encode','video','validate','video')]):
                full['edges'].append({'id':'extra'+str(i),'source':{'node':a,'port':ap},'target':{'node':b,'port':bp}})
            f=s.create('full',{'definition_id':full['id'],'definition_revision':1,'asset_id':asset['asset_id'],'options':{'source_language':'ko','target_language':'ko','video_description':''}},lambda:full,lambda:asset)
            fp=s.plan(f['id'],p)
            with self.assertRaises(ValueError):s.confirm(f['id'],1,fp['token'],False,p)
            s.confirm(f['id'],1,fp['token'],True,p)
            result=s.run(f['id'],p,source,lambda pref,opt:MediaNodeExecutor(pref,opt,provider=FixtureProvider(),paid_allowed=True))
            self.assertEqual(result['status'],'completed',result.get('error'))
            self.assertTrue(s.artifact_path(f['id'],'encode','video').is_file())
            self.assertTrue(json.loads(s.artifact_path(f['id'],'validate','report').read_text())['valid'])
            import os,shutil
            if os.getenv('WF03_CPU_EVIDENCE_DIR'):
                output=Path(os.environ['WF03_CPU_EVIDENCE_DIR']);output.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(s.artifact_path(f['id'],'encode','video'),output/'synthetic-cpu-fixture-provider.mp4')
                shutil.copyfile(s.artifact_path(f['id'],'srt','subtitles'),output/'fixture-provider-subtitles.srt')
                shutil.copyfile(s.artifact_path(f['id'],'validate','report'),output/'actual-validation.json')
                (output/'actual-ticket.json').write_text(json.dumps({'mode':'Synthetic CPU FFmpeg + deterministic STT/translation provider, no real cloud inference','ticket':result},ensure_ascii=False,indent=2))

    def test_ticket_api_create_confirm_no_auto_run_and_real_fixture_artifact(self):
        import subprocess,sys
        probe=subprocess.run([sys.executable,'-c','import app.api.workflow_ticket_routes'],capture_output=True,text=True)
        self.assertEqual(probe.returncode,0,probe.stderr)
        import tempfile,json
        from uuid import uuid4
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import settings_routes
        from video_service.workflow_definitions import DefinitionStore
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);asset_dir=root/'.assets'/('b'*32);asset_dir.mkdir(parents=True);source=asset_dir/'source.mp4';source.write_bytes(b'isolated deterministic fixture')
            (asset_dir/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'fixture.mp4','size_bytes':source.stat().st_size}))
            d=graph();d['revision']=0;DefinitionStore(root).save('a'*32,d)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)):
                app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
                with TestClient(app) as client:
                    base='/api/settings/workflow-tickets'
                    self.assertEqual(client.get(base+'/runtime').status_code,200)
                    created=client.post(base,json={'request_id':str(uuid4()),'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}})
                    self.assertEqual(created.status_code,201,created.text);t=created.json();self.assertEqual(t['status'],'held')
                    path=base+'/'+t['id'];plan=client.get(path+'/plan').json()
                    confirmed=client.post(path+'/confirm',json={'revision':t['revision'],'token':plan['token'],'paid_confirmed':False})
                    self.assertEqual(confirmed.status_code,200);revision=confirmed.json()['revision']
                    body={'revision':revision,'token':plan['token']}
                    self.assertEqual(client.post(path+'/start',json=body).status_code,409)
                    self.assertEqual(client.get(path).json()['status'],'confirmed')
                    def factory(p,o):
                        def execute(step,inputs,work,check):
                            result={}
                            for port in step['outputs']:
                                f=work/(port+'.fixture');f.write_bytes(b'actual deterministic fixture artifact');result[port]=f
                            return result
                        return execute
                    app.state.workflow_executor_factory=factory
                    from approval_fixtures import approved_post
                    result=approved_post(client,path+'/start',json=body)
                    self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['status'],'completed')
                    downloaded=client.get(path+'/artifacts/extract/audio')
                    self.assertEqual(downloaded.content,b'actual deterministic fixture artifact')
                    self.assertIn('extract-audio.fixture',downloaded.headers['content-disposition'])
                    import threading
                    from concurrent.futures import ThreadPoolExecutor
                    started=threading.Event();release=threading.Event()
                    old_factory=factory
                    def blocking_factory(p,o):
                        execute=old_factory(p,o)
                        def run(step,inputs,work,check):
                            started.set();release.wait(timeout=2);return execute(step,inputs,work,check)
                        return run
                    app.state.workflow_executor_factory=blocking_factory
                    other=client.post(base,json={'request_id':str(uuid4()),'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}}).json()
                    other_path=base+'/'+other['id'];other_plan=client.get(other_path+'/plan').json()
                    c=client.post(other_path+'/confirm',json={'revision':1,'token':other_plan['token'],'paid_confirmed':False}).json()
                    with ThreadPoolExecutor() as pool:
                        future=pool.submit(approved_post,client,other_path+'/start',json={'revision':c['revision'],'token':other_plan['token']})
                        self.assertTrue(started.wait(timeout=1))
                        try:self.assertEqual(client.get(other_path).json()['status'],'running')
                        finally:release.set()
                        self.assertEqual(future.result().json()['status'],'completed')

    def test_node_transcript_original_clock_reuse_and_corruption_refusal(self):
        import tempfile,json
        from pathlib import Path
        from media_agent.sequential_nodes import MediaNodeExecutor
        from video_service.transcript import TranscriptSegment
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);audio=root/'packed.wav';audio.write_bytes(b'isolated fixture packed audio');timeline=root/'timeline.json'
            timeline.write_text(json.dumps([{'processed_start':0,'processed_end':1,'original_start':10,'original_end':11}]))
            class Provider:
                transcription_identity='fixture-clock';calls=0
                def transcribe(self,*a,**k):self.calls+=1;return [TranscriptSegment(.1,.2,'clock fixture')]
            provider=Provider();adapter=MediaNodeExecutor({}, {'source_language':'en'}, provider=provider,paid_allowed=True);work=root/'node';work.mkdir()
            step={'type':'transcribe','options':{}}
            result=adapter(step,{'audio':audio,'timeline':timeline},work,lambda:None)
            cues=json.loads(result['transcript'].read_text());self.assertAlmostEqual(cues[0]['start'],10.1)
            adapter(step,{'audio':audio,'timeline':timeline},work,lambda:None);self.assertEqual(provider.calls,1)
            p=work/'completed-transcript.json';d=json.loads(p.read_text());d['cues'][0]['text']='tampered';p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):adapter(step,{'audio':audio,'timeline':timeline},work,lambda:None)
            self.assertEqual(provider.calls,1)

    def test_unplanned_vocalization_calls_are_not_silently_enabled(self):
        import os
        from unittest.mock import patch
        from video_service.sequential_workflow import compile_sequence
        with patch.dict(os.environ,{'VOCALIZATION_FILTER_ENABLED':'true'}):
            self.assertFalse(compile_sequence(graph())['supported'])
