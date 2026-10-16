import importlib.util
import tempfile
import unittest
from pathlib import Path
import json
from test_workflow_decision import decision_graph
from video_service.model_registry import ModelRegistry


class BoundWorkTests(unittest.TestCase):
    def test_registry_pin_drives_real_decision_path_and_survives_disable_after_judgment(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.work_tickets'),'Registered workflow ticket implementation missing')
        from video_service.work_tickets import WorkTicketStore, decision_descriptor
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=ModelRegistry(root)
            old=registry.save('c'*32,{'revision':0,'name':'Pinned model','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
            graph=decision_graph();graph['nodes'][0]['model_ref']={'model_id':'c'*32,'revision':1}
            source=root/'controlled.bin';source.write_bytes(b'controlled fixture input')
            asset={'asset_id':'b'*32,'size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
            store=WorkTicketStore(root)
            ticket=store.create('new-work',{'definition_id':graph['id'],'definition_revision':1,'asset_id':'b'*32,'options':{}},lambda:graph,lambda:asset)
            newer=registry.save('c'*32,{'revision':old['revision'],'name':'Explicit new version','provider':'openai','model':'gpt-4o','uses':['decision']})
            calls=[];native=[]
            def factory(bound,options,admitted,bindings):
                class Provider:
                    descriptor=decision_descriptor(bound['model_binding']) if bound.get('model_binding') else None
                    def decide(self,context):
                        calls.append(bound['model_binding'])
                        return {'version':1,'label':'pass' if bound['decision_model']=='gpt-4o-mini' else 'reject','confidence':.9,'reason':'controlled client uses the actual registered/pinned model config, NOT live inference'}
                def execute(step,inputs,work,check):
                    native.append(step['id'])
                    result={}
                    for port in step['outputs']:
                        p=work/(port+'.fixture');p.write_text('{}');result[port]=p
                    return result
                execute.decision_provider=Provider()
                return execute
            prefs={'revision':0,'api_keys':{}}
            def run(number):
                current=store.get(ticket['id']);plan=store.plan(ticket['id'],prefs)
                confirmed=store.confirm(ticket['id'],current['revision'],plan['token'],bool(plan['paid_roles']),prefs)
                return store.run(ticket['id'],prefs,source,factory,request_id='step-'+str(number),revision=confirmed['revision'],token=plan['token'],operation='start' if number==0 else 'continue')
            first=run(0)
            self.assertEqual(first['status'],'awaiting_decision',first)
            self.assertEqual(first['model_bindings']['judge']['revision'],1)
            self.assertEqual(calls[0]['model'],'gpt-4o-mini')
            self.assertEqual(first['decisions']['judge']['selected_port'],'a')
            registry.set_active('c'*32,newer['revision'],False)
            second=run(1)
            self.assertEqual(second['status'],'awaiting_review',second)
            self.assertEqual(len(calls),1)
            doc=store.review_document(ticket['id'],'gate');view=doc.get()
            doc.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'explicit-human')
            final=run(2)
            self.assertEqual(final['status'],'completed',final)
            self.assertEqual(len(calls),1)
            self.assertEqual(native,['independent','a'])
            self.assertEqual(json.loads(store.artifact_path(ticket['id'],'joined','manifest').read_text())['kind'],'artifact_manifest')
            self.assertEqual(final['model_bindings'],first['model_bindings'])

    def test_product_preview_is_readonly_and_bound_create_rechecks_model_availability(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from uuid import uuid4
        from video_service.workflow_definitions import DefinitionStore
        from video_service.model_registry import ModelRegistry
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=ModelRegistry(root)
            model=registry.save('c'*32,{'revision':0,'name':'registered','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
            graph=decision_graph();graph.pop('id');graph['revision']=0;graph['nodes'][0]['model_ref']={'model_id':'c'*32,'revision':1}
            DefinitionStore(root).save('a'*32,graph)
            assets=root/'.assets'/('b'*32);assets.mkdir(parents=True);(assets/'source.mp4').write_bytes(b'controlled fixture input')
            (assets/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'fixture.mp4','size_bytes':(assets/'source.mp4').stat().st_size}))
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)),TestClient(app) as client:
                selection={'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}}
                quoted=client.post('/api/settings/work-entry/preview',json=selection)
                self.assertEqual(quoted.status_code,200,quoted.text)
                plan=quoted.json()
                self.assertEqual(plan['model_bindings']['judge']['model'],'gpt-4o-mini')
                self.assertFalse(any(root.glob('.workflow-work-tickets/*/*/ticket.json')))
                request={**selection,'request_id':str(uuid4()),'token':plan['token'],'paid_confirmed':True}
                registry.set_active('c'*32,model['revision'],False)
                rejected=client.post('/api/settings/work-entry/create',json=request)
                self.assertEqual(rejected.status_code,409,rejected.text)
                self.assertFalse(any(root.glob('.workflow-work-tickets/*/*/ticket.json')))
                current=registry.get('c'*32);registry.set_active('c'*32,current['revision'],True)
                refreshed=client.post('/api/settings/work-entry/preview',json=selection).json()
                self.assertNotEqual(plan['token'],refreshed['token'])
                created=client.post('/api/settings/work-entry/create',json={**request,'token':refreshed['token']})
                self.assertEqual(created.status_code,201,created.text)
                self.assertEqual(created.json()['status'],'confirmed')
                self.assertEqual(created.json()['model_bindings']['judge']['revision'],1)
                self.assertEqual(client.get('/api/settings/work-tickets/'+created.json()['id']).status_code,200)

    def test_registered_transport_receives_pinned_provider_model_not_global_role(self):
        self.assertIsNotNone(importlib.util.find_spec('media_worker.registered_nodes'),'Registered native/client adapter missing')
        from media_worker.registered_nodes import RegisteredDecisionProvider
        from video_service.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as directory:
            registry=ModelRegistry(directory)
            registry.save('c'*32,{'revision':0,'name':'bound','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
            binding=registry.resolve({'model_id':'c'*32,'revision':1},'decision')
            calls=[]
            def transport(provider,model,key,context):
                calls.append({'provider':provider,'model':model,'key_present':bool(key),'context':context})
                return {'version':1,'label':'review','confidence':.5,'reason':'controlled request transport, NOT live model'}
            prefs={'decision_provider':'openai','decision_model':'gpt-4o-mini','translation_model':'different-global-model','model_binding':binding,'api_keys':{'openai':''}}
            adapter=RegisteredDecisionProvider(prefs,paid_allowed=True,transport=transport)
            self.assertEqual(adapter.decide({'content':{'controlled':True}})['label'],'review')
            self.assertEqual(calls[0]['provider'],'openai')
            self.assertEqual(calls[0]['model'],'gpt-4o-mini')
            self.assertEqual(adapter.descriptor['revision'],'1')
            with self.assertRaises(PermissionError):
                RegisteredDecisionProvider(prefs,paid_allowed=False,transport=transport).decide({})
            self.assertEqual(len(calls),1)

    def test_disable_before_start_rejects_old_confirmation_then_preserves_independent_result(self):
        from work_fixtures import WorkHarness
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            h=WorkHarness(directory)
            confirmed,plan=h.confirm();h.stop()
            with self.assertRaises(TicketConflict):
                h.run(confirmed=confirmed,plan=plan)
            self.assertEqual(h.calls,[])
            self.assertEqual(h.native,[])
            failed=h.run()
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(h.calls,[])
            steps={n['id']:n for n in failed['steps']}
            self.assertEqual(steps['judge']['error_type'],'ModelUnavailable')
            self.assertEqual(steps['a']['status'],'blocked')
            self.assertEqual(steps['independent']['status'],'succeeded')
            self.assertEqual(h.store.artifact_path(failed['id'],'independent','metadata').read_text(),'{}')
            revision=failed['revision'];active=h.registry.get('c'*32)
            h.registry.set_active('c'*32,active['revision'],True)
            self.assertEqual(h.store.get(failed['id'])['revision'],revision)
            self.assertEqual(h.store.get(failed['id'])['status'],'failed')
            self.assertEqual(h.calls,[])

    def test_disable_before_continuation_does_not_rejudge_or_destroy_completed_artifacts(self):
        from work_fixtures import WorkHarness
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            h=WorkHarness(directory,dual=True)
            first=h.run();self.assertEqual(first['status'],'awaiting_decision')
            report=first['decisions']['judge'];independent=h.store.artifact_path(first['id'],'independent','metadata').read_bytes()
            confirmed,plan=h.confirm();h.stop()
            with self.assertRaises(TicketConflict):
                h.run('continue',confirmed,plan)
            self.assertEqual(len(h.calls),1)
            failed=h.run('continue')
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(len(h.calls),1)
            self.assertEqual(failed['decisions']['judge'],report)
            self.assertEqual(h.store.artifact_path(first['id'],'independent','metadata').read_bytes(),independent)
            self.assertEqual(next(n for n in failed['steps'] if n['id']=='gate')['error_type'],'ModelUnavailable')
            self.assertEqual(next(n for n in failed['steps'] if n['id']=='a')['status'],'blocked')

    def test_registered_executor_uses_real_synthetic_cpu_output_not_media_fixture(self):
        import subprocess
        from work_fixtures import WorkHarness
        from media_worker.registered_nodes import RegisteredMediaExecutor
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(source)]))
            h=WorkHarness(directory,source=source)
            def transport(provider,model,key,context):
                h.calls.append({'provider':provider,'model':model})
                return {'version':1,'label':'pass','confidence':.9,'reason':'registered config + controlled JSON request, actual CPU media ONLY'}
            def factory(bound,options,admitted,bindings):
                executor=RegisteredMediaExecutor(bound,options,source,admitted,paid_allowed=True,decision_transport=transport)
                executor.review_duration=float(probe['format']['duration'])
                return executor
            h.factory=factory
            self.assertEqual(h.run()['status'],'awaiting_decision')
            current=h.run('continue');self.assertEqual(current['status'],'awaiting_review',current)
            document=h.store.review_document(current['id'],'gate');view=document.get()
            document.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'explicit-human')
            final=h.run('continue');self.assertEqual(final['status'],'completed',final)
            output=h.store.artifact_path(final['id'],'a','video')
            result=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
            self.assertEqual(next(s for s in result['streams'] if s['codec_type']=='video')['codec_name'],'h264')
            self.assertEqual(h.calls,[{'provider':'openai','model':'gpt-4o-mini'}])

    def test_step_snapshot_records_effective_fixed_model_fallback_policy(self):
        from work_fixtures import WorkHarness
        with tempfile.TemporaryDirectory() as directory:
            h=WorkHarness(directory)
            h.preferences.update(fallback_on_error=True,fallback_on_block=True)
            result=h.run()
            step=next(row for row in result['steps'] if row['id']=='judge')
            self.assertFalse(step['serving_snapshot']['fallback_on_error'])
            self.assertFalse(step['serving_snapshot']['fallback_on_block'])
            self.assertEqual(step['serving_snapshot']['decision_fallback_model'],'')
            self.assertTrue(result['settings_snapshot']['fallback_on_error'])


if __name__=='__main__':
    unittest.main()
