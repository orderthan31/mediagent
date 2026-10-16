"""WF07 approved A; actual isolated persistence, no providers or user media."""
from pathlib import Path
import tempfile
import unittest
from test_sequential_workflow import graph
from video_service.workflow_definitions import DefinitionStore, DefinitionConflict


class RecoveryTicketTests(unittest.TestCase):
    def test_cancel_before_start_can_fork_without_claiming_prior_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder))
            old_token=s.plan(ticket['id'],prefs)['token']
            cancelled=s.cancel(ticket['id'],0,'cancel')
            child=s.fork(ticket['id'],'recover-held',cancelled['revision'],source)
            self.assertNotEqual(s.plan(child['id'],prefs)['token'],old_token)
            self.assertEqual(child['status'],'held')
            self.assertEqual(child['reuse_origins'],{})
            self.assertFalse(child['recovery_risk']['unknown_nodes'])
            child_token=s.plan(child['id'],prefs)['token']
            cancelled_child=s.cancel(child['id'],child['control_revision'],'cancel-child')
            grandchild=s.fork(child['id'],'recover-again',cancelled_child['revision'],source)
            self.assertNotEqual(s.plan(grandchild['id'],prefs)['token'],child_token)

    def test_approved_waiting_gate_is_reused_without_a_new_human_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder))
            def factory(*args):
                def execute(step,inputs,work,check):
                    p=work/'video.fixture';p.write_bytes(b'completed');return {'video':p}
                return execute
            plan=s.plan(ticket['id'],prefs);c=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            waiting=s.run(ticket['id'],prefs,source,factory,request_id='run',revision=c['revision'],token=plan['token'],operation='start')
            doc=s.review_document(ticket['id'],'after');view=doc.get();approved=doc.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'approve')
            cancelled=s.cancel(ticket['id'],waiting['control_revision'],'cancel')
            child=s.fork(ticket['id'],'recover',cancelled['revision'],source)
            self.assertEqual(child['reviews']['after']['approval'],approved['approval'])
            plan=s.plan(child['id'],prefs);c=s.confirm(child['id'],child['revision'],plan['token'],False,prefs)
            final=s.run(child['id'],prefs,source,factory,request_id='run',revision=c['revision'],token=plan['token'],operation='start')
            self.assertEqual(final['status'],'completed',final)

    def test_interrupted_finalization_reuses_all_receipts_without_new_calls(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder));calls=[]
            def factory(*args):
                def execute(step,inputs,work,check):
                    calls.append(step['id']);p=work/'video.fixture';p.write_bytes(b'completed');return {'video':p}
                return execute
            plan=s.plan(ticket['id'],prefs);c=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            s.run(ticket['id'],prefs,source,factory,request_id='run',revision=c['revision'],token=plan['token'],operation='start')
            doc=s.review_document(ticket['id'],'after');view=doc.get();doc.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'approve')
            plan=s.plan(ticket['id'],prefs);c=s.confirm(ticket['id'],s.get(ticket['id'])['revision'],plan['token'],False,prefs)
            save=s._save
            def interrupted(record):
                if record['status']=='completed':raise SystemExit('interrupted only terminal publication')
                return save(record)
            with patch.object(s,'_save',side_effect=interrupted),self.assertRaises(SystemExit):
                s.run(ticket['id'],prefs,source,factory,request_id='continue',revision=c['revision'],token=plan['token'],operation='continue')
            old=s.get(ticket['id']);child=s.fork(ticket['id'],'finalize',old['revision'],source)
            plan=s.plan(child['id'],prefs);self.assertTrue(plan['ready']);self.assertTrue(plan['finalization_only'])
            c=s.confirm(child['id'],child['revision'],plan['token'],False,prefs)
            final=s.run(child['id'],prefs,source,factory,request_id='finalize',revision=c['revision'],token=plan['token'],operation='start')
            self.assertEqual(final['status'],'completed');self.assertEqual(calls,['first'])

    def test_interrupted_child_copy_reuses_the_same_admitted_identity(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder))
            def factory(*args):
                def execute(step,inputs,work,check):
                    p=work/'video.fixture';p.write_bytes(b'completed');return {'video':p}
                return execute
            plan=s.plan(ticket['id'],prefs);c=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            waiting=s.run(ticket['id'],prefs,source,factory,request_id='run',revision=c['revision'],token=plan['token'],operation='start')
            cancelled=s.cancel(ticket['id'],waiting['control_revision'],'cancel')
            with patch('video_service.recovery_tickets.shutil.copyfile',side_effect=OSError('interrupted new-child copy')):
                with self.assertRaises(OSError):s.fork(ticket['id'],'recover-once',cancelled['revision'],source)
            def no_space(size):
                self.assertGreater(size,0)
                raise RuntimeError('controlled capacity rejection before copying')
            with self.assertRaisesRegex(RuntimeError,'capacity rejection'):
                s.fork(ticket['id'],'recover-once',cancelled['revision'],source,capacity_check=no_space)
            child=s.fork(ticket['id'],'recover-once',cancelled['revision'],source)
            directories=[p for p in s.directory.iterdir() if p.is_dir() and len(p.name)==32]
            self.assertEqual(len(directories),2,'retry must resume one admitted child, not allocate orphan child identities')
            self.assertEqual(s.fork(ticket['id'],'recover-once',cancelled['revision'],source)['id'],child['id'])

    def test_missing_child_receipt_is_blocked_before_new_plan(self):
        from video_service.workflow_tickets import TicketConflict
        from video_service.storage import read_json,write_json_atomic
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder))
            def factory(*args):
                def execute(step,inputs,work,check):
                    p=work/'video.fixture';p.write_bytes(b'completed');return {'video':p}
                return execute
            plan=s.plan(ticket['id'],prefs);c=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            waiting=s.run(ticket['id'],prefs,source,factory,request_id='run',revision=c['revision'],token=plan['token'],operation='start')
            cancelled=s.cancel(ticket['id'],waiting['control_revision'],'cancel')
            child=s.fork(ticket['id'],'recover',cancelled['revision'],source)
            path=s.directory_for(child['id'])/'ticket.json';row=read_json(path);row['receipts'].pop('first');write_json_atomic(path,row)
            with self.assertRaises(TicketConflict):s.plan(child['id'],prefs)

    def test_recovery_keeps_judgment_approval_and_disabled_model_result(self):
        from work_fixtures import WorkHarness
        from video_service.recovery_tickets import RecoveryTicketStore
        with tempfile.TemporaryDirectory() as folder:
            h=WorkHarness(Path(folder));h.store=RecoveryTicketStore(Path(folder))
            h.ticket=h.store.create('opt-in',{'definition_id':h.graph['id'],'definition_revision':1,'asset_id':h.asset['asset_id'],'options':{}},lambda:h.graph,lambda:h.asset)
            first=h.run();self.assertEqual(first['status'],'awaiting_decision')
            second=h.run('continue');self.assertEqual(second['status'],'awaiting_review')
            doc=h.store.review_document(h.ticket['id'],'gate');view=doc.get()
            approved=doc.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'approved')
            original_factory=h.factory
            def failing_factory(*args):
                original=original_factory(*args)
                def execute(step,*args):
                    if step['id']=='a':raise RuntimeError('controlled downstream failure')
                    return original(step,*args)
                execute.decision_provider=original.decision_provider
                return execute
            h.factory=failing_factory
            failed=h.run('continue');self.assertEqual(failed['status'],'failed',failed)
            h.stop()
            child=h.store.fork(failed['id'],'recover',failed['revision'],h.source)
            self.assertEqual(child['reviews']['gate']['approval'],approved['approval'])
            h.ticket=child;h.factory=original_factory
            final=h.run();self.assertEqual(final['status'],'completed',final)
            self.assertEqual(len(h.calls),1)
            self.assertEqual(h.native.count('independent'),1)
            self.assertEqual(final['decisions']['judge'],first['decisions']['judge'])
            self.assertFalse(final['model_availability']['judge']['active'])

    def test_crash_requires_separate_risk_ack_and_retires_old_generation(self):
        from video_service.recovery_tickets import RecoveryTicketStore
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as folder:
            s,ticket,source,prefs=self.simple(Path(folder))
            def factory(*args):
                def interrupted(*args):raise SystemExit('simulated coordinator/process interruption')
                return interrupted
            plan=s.plan(ticket['id'],prefs);current=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            with self.assertRaises(SystemExit):
                s.run(ticket['id'],prefs,source,factory,request_id='run',revision=current['revision'],token=plan['token'],operation='start')
            old=s.get(ticket['id']);self.assertEqual(old['status'],'running')
            with self.assertRaises(TicketConflict):s.fork(old['id'],'retry',old['revision'],source)
            child=s.fork(old['id'],'retry-risk',old['revision'],source,risk_confirmed=True)
            self.assertTrue(child['recovery_risk']['acknowledged'])
            self.assertEqual(child['recovery_risk']['unknown_nodes'],['first'])
            self.assertIsNone(child['confirmation']);self.assertEqual(child['status'],'held')
            before=(s.directory_for(old['id'])/'ticket.json').read_bytes()
            with self.assertRaises(TicketConflict):s._save(old)
            self.assertEqual((s.directory_for(old['id'])/'ticket.json').read_bytes(),before)
            self.assertTrue(list((s.directory_for(old['id'])/'late-results').glob('*.json')))
            self.assertEqual(RecoveryTicketStore(Path(folder)).get(child['id'])['status'],'held')

    def test_cancel_persists_and_prevents_followup_dispatch(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from video_service.recovery_tickets import RecoveryTicketStore
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as folder:
            s, ticket, source, prefs = self.simple(Path(folder))
            entered,release=Event(),Event();calls=[]
            def factory(*args):
                def execute(step,inputs,work,check):
                    calls.append(step['id'])
                    if step['id']=='first':entered.set();self.assertTrue(release.wait(5))
                    output=work/'video.fixture';output.write_bytes(b'completed late output');return {'video':output}
                return execute
            plan=s.plan(ticket['id'],prefs);confirmed=s.confirm(ticket['id'],ticket['revision'],plan['token'],False,prefs)
            with ThreadPoolExecutor() as pool:
                running=pool.submit(s.run,ticket['id'],prefs,source,factory,request_id='run',revision=confirmed['revision'],token=plan['token'],operation='start')
                try:
                    self.assertTrue(entered.wait(3))
                    other=RecoveryTicketStore(Path(folder))
                    current=other.get(ticket['id'])
                    cancelled=other.cancel(ticket['id'],current['control_revision'],'cancel-once')
                    self.assertEqual(cancelled['status'],'cancelling')
                    self.assertEqual(other.cancel(ticket['id'],current['control_revision'],'cancel-once')['control_revision'],cancelled['control_revision'])
                    with self.assertRaises(TicketConflict):other.cancel(ticket['id'],current['control_revision'],'stale-cancel')
                finally:release.set()
                final=running.result(timeout=5)
            self.assertEqual(final['status'],'cancelled');self.assertEqual(calls,['first'])
            self.assertTrue(s.artifact_path(ticket['id'],'first','video').is_file())
            self.assertEqual(final['steps'][0]['status'],'quarantined')
            self.assertEqual(final['scheduler']['nodes']['first']['status'],'quarantined')
            self.assertNotIn('result',final['scheduler']['nodes']['first'])
            self.assertNotIn('first',final['receipts'])
            self.assertEqual(final['recovery_unknown_nodes'],['first'])
            with self.assertRaises(TicketConflict):s.fork(ticket['id'],'retry-without-risk',final['revision'],source)
            child=s.fork(ticket['id'],'retry-after-quarantine',final['revision'],source,risk_confirmed=True)
            self.assertEqual(child['steps'][0]['status'],'pending')
            self.assertNotIn('first',child['reuse_origins'])
            self.assertEqual(final['steps'][1]['artifacts'],{})

    @staticmethod
    def simple(root):
        from video_service.recovery_tickets import RecoveryTicketStore
        source=root/'source.fixture';source.write_bytes(b'controlled bytes')
        definition={'id':'a'*32,'revision':1,'catalog_version':1,'name':'cancel chain','inputs':{'video':'video'},
                    'nodes':[{'id':n,'type':'encode' if i==0 else 'review','options':{'subtitle_mode':'none'} if i==0 else {'data_type':'video'},'position':{'x':i*200,'y':0}} for i,n in enumerate(['first','after'])],
                    'edges':[{'id':'e0','source':{'node':'$input','port':'video'},'target':{'node':'first','port':'video'}},
                             {'id':'e1','source':{'node':'first','port':'video'},'target':{'node':'after','port':'value'}}]}
        asset={'asset_id':'b'*32,'size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
        from video_service.work_tickets import compile_work
        compiled=compile_work({k:v for k,v in definition.items() if k!='id'},{})
        assert compiled['supported'],compiled['reasons']
        store=RecoveryTicketStore(root)
        ticket=store.create('create',{'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}},lambda:definition,lambda:asset)
        return store,ticket,source,{'revision':0,'api_keys':{}}

    def test_failed_ticket_forks_once_and_reuses_completed_join(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('video_service.recovery_tickets'), 'Opt-in recovery tickets missing')
        from video_service.recovery_tickets import RecoveryTicketStore
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'input.fixture';source.write_bytes(b'isolated input')
            definition={'id':'a'*32,'revision':1,'catalog_version':1,'name':'recovery join','inputs':{'video':'video'},
                'nodes':[{'id':n,'type':t,'options':o,'position':{'x':i*200,'y':0}} for i,(n,t,o) in enumerate([
                    ('a','encode',{'subtitle_mode':'none'}),('b','encode',{'subtitle_mode':'none'}),
                    ('join','join',{'left_type':'video','right_type':'video'}),('failure','analyze',{})])],
                'edges':[{'id':'e'+str(i),'source':{'node':a,'port':p},'target':{'node':b,'port':q}} for i,(a,p,b,q) in enumerate([
                    ('$input','video','a','video'),('$input','video','b','video'),('a','video','join','left'),('b','video','join','right'),('$input','video','failure','video')])]}
            asset={'asset_id':'b'*32,'size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
            s=RecoveryTicketStore(root);identity={'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}}
            ticket=s.create('create',identity,lambda:definition,lambda:asset);prefs={'revision':0,'api_keys':{}};calls=[];fail=[True]
            def factory(*args):
                def execute(step,inputs,work,check):
                    calls.append(step['id'])
                    if step['id']=='failure' and fail[0]:raise RuntimeError('controlled failure')
                    outputs={}
                    for port in step['outputs']:
                        p=work/(port+'.fixture');p.write_text('{}');outputs[port]=p
                    return outputs
                return execute
            def run(t):
                plan=s.plan(t['id'],prefs);confirmed=s.confirm(t['id'],s.get(t['id'])['revision'],plan['token'],False,prefs)
                return s.run(t['id'],prefs,source,factory,request_id='start',revision=confirmed['revision'],token=plan['token'],operation='start')
            parent=run(ticket);self.assertEqual(parent['status'],'failed');self.assertIn('join',parent['receipts'])
            before=(s.directory_for(parent['id'])/'ticket.json').read_bytes()
            artifact=s.artifact_path(parent['id'],'a','video');original_bytes=artifact.read_bytes();artifact.write_bytes(b'changed output')
            with self.assertRaises(TicketConflict):s.fork(parent['id'],'tampered-output',parent['revision'],source)
            artifact.write_bytes(original_bytes)
            from video_service.storage import read_json,write_json_atomic
            path=s.directory_for(parent['id'])/'ticket.json';tampered=read_json(path);tampered['receipts'].pop('join');write_json_atomic(path,tampered)
            with self.assertRaises(TicketConflict):s.fork(parent['id'],'missing-receipt',parent['revision'],source)
            path.write_bytes(before)
            tampered=read_json(path);tampered['definition']['name']='tampered snapshot name';write_json_atomic(path,tampered)
            with self.assertRaises(TicketConflict):s.fork(parent['id'],'changed-definition',parent['revision'],source)
            path.write_bytes(before)
            import shutil
            foreign=RecoveryTicketStore(root,'foreign-owner');foreign.directory.mkdir(parents=True)
            shutil.copytree(s.directory_for(parent['id']),foreign.directory_for(parent['id']))
            with self.assertRaises(TicketConflict):foreign.fork(parent['id'],'foreign',parent['revision'],source)
            child=s.fork(parent['id'],'recover-once',parent['revision'],source)
            again=s.fork(parent['id'],'recover-once',parent['revision'],source)
            self.assertEqual(child['id'],again['id']);self.assertEqual(child['status'],'held')
            self.assertEqual((s.directory_for(parent['id'])/'ticket.json').read_bytes(),before)
            fail[0]=False;final=run(child);self.assertEqual(final['status'],'completed')
            self.assertEqual(calls.count('a'),1);self.assertEqual(calls.count('b'),1);self.assertEqual(calls.count('failure'),2)
            self.assertEqual(final['recovery_parent']['ticket_id'],parent['id'])
            self.assertEqual(final['reuse_origins']['join']['ticket_id'],parent['id'])
            self.assertTrue(s.artifact_path(parent['id'],'join','manifest').is_file())
            with self.assertRaises(TicketConflict):s.cancel(final['id'],final['control_revision'],'too-late')


class RecoveryApiTests(unittest.TestCase):
    def test_opt_in_preview_has_a_separate_bound_token(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.api import work_entry_routes as entry, settings_routes
        self.assertIn('recovery_enabled',entry.PreviewRequest.model_fields)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store,ticket,source,prefs=RecoveryTicketTests.simple(root)
            payload={k:ticket['definition'][k] for k in ('catalog_version','revision','name','inputs','nodes','edges')};payload['revision']=0
            DefinitionStore(root).save('a'*32,payload)
            request=SimpleNamespace(state=SimpleNamespace(settings_owner=None))
            common={'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32}
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root)),patch.object(entry,'asset_input',return_value=(ticket['asset'],source)),patch.object(entry,'preferences',return_value=prefs):
                old=entry.preview_inputs(request,entry.PreviewRequest(**common))[-1]
                new=entry.preview_inputs(request,entry.PreviewRequest(**common,recovery_enabled=True))[-1]
                self.assertNotEqual(old['token'],new['token'])
                self.assertTrue(new['recovery_enabled'])
                self.assertEqual(len(store.list()),1)

    def test_new_namespace_cancel_and_history_api_preserve_old_tickets(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);s,ticket,source,prefs=RecoveryTicketTests.simple(root)
            definitions=DefinitionStore(root);definition=graph();definition.pop('id',None);definition['revision']=0
            saved=definitions.save('d'*32,definition)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)),TestClient(app) as client:
                response=client.get('/api/settings/recovery-tickets')
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(len(response.json()['tickets']),1)
                self.assertEqual(client.get('/api/settings/work-tickets').json()['tickets'],[])
                path='/api/settings/recovery-tickets/'+ticket['id']
                cancelled=client.post(path+'/cancel',json={'request_id':'11111111-1111-4111-8111-111111111111','control_revision':0})
                self.assertEqual(cancelled.status_code,200,cancelled.text)
                self.assertEqual(cancelled.json()['status'],'cancelled')
                self.assertEqual(client.post('/api/settings/work-tickets/'+ticket['id']+'/cancel',json={}).status_code,404)
                versions=client.get('/api/settings/workflow-definitions/'+saved['id']+'/versions')
                self.assertEqual(versions.status_code,200,versions.text)
                self.assertEqual(versions.json()['versions'][0]['revision'],1)
                restored=client.post('/api/settings/workflow-definitions/'+saved['id']+'/restore',json={'revision':1,'source':{'kind':'definition_revision','revision':1}})
                self.assertEqual(restored.status_code,200,restored.text)
                self.assertEqual(restored.json()['revision'],2)
                from_ticket=client.post('/api/settings/workflow-definitions/'+saved['id']+'/restore',json={'revision':2,'source':{'kind':'ticket_snapshot','namespace':'recovery','ticket_id':ticket['id']}})
                self.assertEqual(from_ticket.status_code,200,from_ticket.text)
                self.assertEqual(from_ticket.json()['revision'],3)
                self.assertEqual(from_ticket.json()['name'],ticket['definition']['name'])
                self.assertEqual(s.get(ticket['id'])['definition']['revision'],1)
                self.assertEqual(definitions.version(saved['id'],3)['source']['ticket_id'],ticket['id'])


class RecoverySchedulerTests(unittest.TestCase):
    def test_denied_dispatch_remains_pending_without_executor_submission(self):
        from video_service.parallel_scheduler import run_ready
        calls=[];published=[]
        result=run_ready([{'id':'after','dependencies':[]}],lambda step:calls.append(step),lambda state:published.append(state),settle=True,admit=lambda step:False)
        self.assertEqual(calls,[])
        self.assertEqual(result['nodes']['after']['status'],'pending')
        self.assertFalse(any(s['nodes']['after']['status']=='running' for s in published))


class DefinitionHistoryTests(unittest.TestCase):
    def test_uncommitted_history_and_nonexistent_past_are_not_restorable(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            store=DefinitionStore(Path(folder));definition=graph();definition.pop('id',None);definition['revision']=0
            import os
            original=os.replace
            def interrupted_head(src,dst):
                if Path(dst)==store.path('a'*32):raise OSError('interrupted head publication')
                return original(src,dst)
            with patch('video_service.workflow_definitions.os.replace',side_effect=interrupted_head):
                with self.assertRaises(OSError):store.save('a'*32,definition)
            self.assertEqual(store.versions('a'*32),[])
            first=store.save('a'*32,definition)
            with self.assertRaises(FileNotFoundError):store.restore('a'*32,first['revision'],{'kind':'definition_revision','revision':99})
            self.assertEqual(store.get('a'*32)['revision'],1)

    def test_new_history_restores_as_new_revision_without_rewinding(self):
        self.assertTrue(hasattr(DefinitionStore, 'versions'), 'Immutable definition history is missing')
        with tempfile.TemporaryDirectory() as folder:
            store = DefinitionStore(Path(folder), 'owner-a')
            definition = graph()
            definition.pop('id', None)
            definition['revision'] = 0
            first = store.save('a'*32, definition)
            payload = {k: first[k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
            payload['name'] = 'changed head'
            second = store.save('a'*32, payload)
            restored = store.restore('a'*32, second['revision'], {'kind':'definition_revision','revision':1})
            self.assertEqual(restored['revision'], 3)
            self.assertEqual(restored['name'], first['name'])
            self.assertEqual(store.version('a'*32, 2)['definition'], second)
            self.assertEqual([r['revision'] for r in store.versions('a'*32)], [1,2,3])
            with self.assertRaises(DefinitionConflict):
                store.restore('a'*32, 2, {'kind':'definition_revision','revision':1})
            self.assertEqual(store.get('a'*32), restored)
            self.assertEqual(DefinitionStore(Path(folder), 'owner-b').versions('a'*32), [])
