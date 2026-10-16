"""WF-06 adapter contract, separate from not-yet-approved routing policy."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def decision_graph():
    specs = [('judge', 'decision', {'data_type': 'video'}), ('gate', 'review', {'data_type': 'video'}), ('a', 'encode', {'subtitle_mode': 'none'}), ('b', 'encode', {'subtitle_mode': 'none'}), ('joined', 'join', {'left_type': 'video', 'right_type': 'video'}), ('independent', 'analyze', {})]
    links = [('$input', 'video', 'judge', 'value'), ('judge', 'a', 'gate', 'value'), ('gate', 'value', 'a', 'video'), ('judge', 'b', 'b', 'video'), ('a', 'video', 'joined', 'left'), ('b', 'video', 'joined', 'right'), ('$input', 'video', 'independent', 'video')]
    return {'id': 'a'*32, 'catalog_version': 1, 'revision': 1, 'name': '격리 구조화 AI 판단', 'inputs': {'video': 'video'}, 'nodes': [{'id': i, 'type': k, 'options': o, 'position': {'x': n*200, 'y': 100}} for n, (i,k,o) in enumerate(specs)], 'edges': [{'id': 'e'+str(n), 'source': {'node': a, 'port': ap}, 'target': {'node': b, 'port': bp}} for n,(a,ap,b,bp) in enumerate(links)]}


class DecisionAdapterTests(unittest.TestCase):
    def test_structured_adapter_is_invoked_and_evidence_binds_real_input(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.decision_adapter'), 'Structured decision adapter contract missing')
        from video_service.decision_adapter import invoke_decision
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'metadata.json'
            source.write_text('{"valid":true}', encoding='utf-8')
            calls = []
            class Provider:
                descriptor = {'id': 'offline-controlled-fixture', 'revision': '1', 'schema_version': 1, 'paid': False}
                def decide(self, context):
                    calls.append(context)
                    self.assert_unused = None
                    return {'version': 1, 'label': 'pass', 'confidence': .9, 'reason': 'Explicit offline fixture read the supplied metadata'}
            meta = {'type': 'media_metadata', 'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            report = invoke_decision(Provider(), meta, source, root / 'output')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['input']['sha256'], meta['sha256'])
            self.assertEqual(calls[0]['content'], {'valid': True})
            self.assertEqual(report['judgment']['label'], 'pass')
            self.assertEqual(report['input'], meta)
            persisted = json.loads((root / 'output/decision.json').read_text())
            self.assertEqual(persisted, report)
            self.assertEqual(source.read_text(), '{"valid":true}')

    def test_existing_report_rejects_before_adapter_invocation(self):
        from video_service.decision_adapter import invoke_decision, DecisionInputError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.json'
            source.write_text('{}')
            output = root / 'work'
            output.mkdir()
            (output / 'decision.json').write_bytes(b'preserved immutable report')
            class Provider:
                descriptor = {'id': 'offline', 'revision': '1', 'schema_version': 1, 'paid': False}
                calls = 0
                def decide(self, context):
                    self.calls += 1
                    return {'version': 1, 'label': 'pass', 'confidence': 1, 'reason': 'fixture'}
            provider = Provider()
            with self.assertRaises(DecisionInputError):
                invoke_decision(provider, {'type': 'media_metadata', 'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}, source, output)
            self.assertEqual(provider.calls, 0)
            self.assertEqual((output / 'decision.json').read_bytes(), b'preserved immutable report')

    def test_server_conditions_require_exactly_one_typed_match(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.decision_conditions'), 'Typed condition evaluator missing')
        from video_service.decision_conditions import evaluate, DecisionConditionError
        from video_service.decision_adapter import DecisionFormatError, structured_result
        valid = {'version': 1, 'label': 'pass', 'confidence': .9, 'reason': 'offline fixture'}
        self.assertEqual(evaluate(valid, {})['selected_port'], 'a')
        self.assertEqual(evaluate({**valid, 'label': 'reject'}, {})['selected_port'], 'b')
        for label in ('pass', 'review'):
            options = {'a_field': 'label', 'a_op': 'eq', 'a_value': 'pass', 'b_field': 'label', 'b_op': 'eq', 'b_value': 'pass'}
            with self.assertRaises(DecisionConditionError):
                evaluate({**valid, 'label': label}, options)
        self.assertEqual(evaluate(valid, {'a_field': 'confidence', 'a_op': 'gte', 'a_value': '0.7'})['selected_port'], 'a')
        for patch in ({'confidence': True}, {'confidence': float('nan')}, {'version': True}, {'label': 'a'}, {'selected_port': 'b'}):
            with self.assertRaises(DecisionFormatError):
                structured_result({**valid, **patch})
        with self.assertRaises(DecisionConditionError):
            evaluate(valid, {'a_op': 'gte'})

    def test_decision_pause_route_confirmation_review_and_no_rejudgment(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.decision_tickets'), 'Decision ticket execution missing')
        from video_service.decision_tickets import DecisionTicketStore
        from video_service.workflow_tickets import TicketConflict
        definition = decision_graph()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.bin'
            source.write_bytes(b'controlled isolated input')
            asset = {'asset_id': 'b'*32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            class Provider:
                descriptor = {'id': 'controlled-fixture', 'revision': '1', 'schema_version': 1, 'paid': False}
                calls = 0
                def decide(self, context):
                    self.calls += 1
                    return {'version': 1, 'label': 'pass', 'confidence': .9, 'reason': 'Explicit controlled fixture result'}
            provider = Provider()
            store = DecisionTicketStore(root, adapter_profile=provider.descriptor)
            ticket = store.create('new', {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {}}, lambda: definition, lambda: asset)
            prefs = {'revision': 0, 'api_keys': {}}
            calls = []
            def factory(bound, options, admitted):
                def execute(step, inputs, work, check):
                    calls.append((step['id'], bound['revision']))
                    return {p: self._output(work / (p+'.fixture'), {'controlled_fixture': True}) for p in step['outputs']}
                execute.decision_provider = provider
                return execute
            def run(number):
                current = store.get(ticket['id'])
                plan = store.plan(ticket['id'], prefs)
                self.assertTrue(plan['ready'], plan)
                self.assertEqual(plan['token'], store.plan(ticket['id'], prefs)['token'])
                current = store.confirm(ticket['id'], current['revision'], plan['token'], bool(plan['paid_roles']), prefs)
                return store.run(ticket['id'], prefs, source, factory, request_id='run-'+str(number), revision=current['revision'], token=plan['token'], operation='start' if number == 0 else 'continue')
            first = run(0)
            self.assertEqual(first['status'], 'awaiting_decision', first)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(calls, [('independent', 0)])
            self.assertTrue(all(n['status'] == 'pending' for n in first['steps'] if n['id'] in {'a','b','gate','joined'}))
            self.assertEqual(first['decisions']['judge']['selected_port'], 'a')
            prefs = {**prefs, 'revision': 1}
            second = run(1)
            self.assertEqual(second['status'], 'awaiting_review', second)
            self.assertEqual(next(n for n in second['steps'] if n['id']=='b')['status'], 'skipped')
            self.assertEqual(provider.calls, 1)
            doc = store.review_document(ticket['id'], 'gate')
            view = doc.get()
            doc.approve(view['state_revision'], view['revision'], view['sha256'], view['target'], 'approve-gate')
            final = run(2)
            self.assertEqual(final['status'], 'completed', final)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(calls, [('independent', 0), ('a', 1)])
            self.assertEqual(next(n for n in final['steps'] if n['id']=='judge')['serving_snapshot']['revision'], 0)
            self.assertEqual(set(json.loads(store.artifact_path(ticket['id'], 'joined', 'manifest').read_text())['members']), {'a.video'})
            self.assertEqual(store.get(ticket['id'])['decisions']['judge'], first['decisions']['judge'])

    @staticmethod
    def _output(path, value):
        path.write_text(json.dumps(value))
        return path

    def test_successful_judgment_is_pinned_against_consistent_report_route_tamper(self):
        from decision_fixtures import Harness
        from video_service.graph_tickets import file_sha
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory, decision_graph())
            first = h.run()
            work = h.store.directory_for(first['id']) / 'work/judge'
            report = json.loads((work/'decision.json').read_text())
            report['judgment']['reason'] = 'tampered after success'
            (work/'decision.json').write_text(json.dumps(report))
            route = json.loads((work/'route.json').read_text())
            route['report_sha256'] = file_sha(work/'decision.json')
            (work/'route.json').write_text(json.dumps(route))
            with self.assertRaises(TicketConflict):
                h.store.plan(first['id'], h.prefs)
            self.assertEqual(len(h.provider.calls), 1)

    def test_b_selection_skips_a_review_and_runs_only_b_after_new_confirmation(self):
        from decision_fixtures import Harness, ControlledProvider
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory, decision_graph(), ControlledProvider({'version': 1, 'label': 'reject', 'confidence': .8, 'reason': 'Explicit fixture label, NOT branch termination'}))
            first = h.run()
            self.assertEqual(first['status'], 'awaiting_decision')
            self.assertEqual(first['decisions']['judge']['selected_port'], 'b')
            self.assertEqual(next(n for n in first['steps'] if n['id']=='a')['status'], 'pending')
            final = h.run()
            self.assertEqual(final['status'], 'completed', final)
            self.assertEqual([n['node'] for n in h.calls], ['independent','b'])
            self.assertEqual(final['reviews'], {})
            self.assertEqual(len(h.provider.calls), 1)
            self.assertEqual(set(json.loads(h.store.artifact_path(final['id'],'joined','manifest').read_text())['members']), {'b.video'})

    def test_each_error_blocks_dependents_not_independent_success(self):
        from decision_fixtures import Harness, ControlledProvider
        cases = [('adapter_error', 'pass', {}, RuntimeError('do not expose provider diagnostics')),
                 ('format_error', 'unknown', {}, None),
                 ('condition_error', 'review', {}, None),
                 ('condition_error', 'pass', {'b_value':'pass'}, None)]
        for code, label, options, error in cases:
            with self.subTest(code=code,label=label), tempfile.TemporaryDirectory() as directory:
                graph = decision_graph()
                graph['nodes'][0]['options'].update(options)
                h = Harness(directory, graph, ControlledProvider({'version':1,'label':label,'confidence':.8,'reason':'controlled fixture'}, error))
                result = h.run()
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['decisions']['judge']['code'], code)
                states = {n['id']:n['status'] for n in result['steps']}
                self.assertEqual(states['independent'], 'succeeded')
                self.assertTrue(all(states[n]=='blocked' for n in ('a','b','gate','joined')), states)
                self.assertNotIn('do not expose provider diagnostics', json.dumps(result))
                self.assertEqual(len(h.provider.calls), 1)

    def test_successful_request_retransmission_never_rejudges_or_reexecutes(self):
        from decision_fixtures import Harness
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory, decision_graph())
            first = h.run()
            replay = h.store.run(first['id'],h.prefs,h.source,h.factory,**h.last)
            self.assertEqual(replay['revision'], first['revision'])
            self.assertEqual(len(h.provider.calls), 1)
            self.assertEqual([c['node'] for c in h.calls], ['independent'])
            with self.assertRaises(TicketConflict):
                h.store.run(first['id'],h.prefs,h.source,h.factory,**{**h.last,'token':'0'*64})
            from video_service.decision_tickets import DecisionTicketStore
            with self.assertRaises(FileNotFoundError):
                DecisionTicketStore(directory, 'other-owner').get(first['id'])

    def test_admission_and_manual_choices_are_not_retrofitted(self):
        from video_service.parallel_workflow import compile_graph
        from video_service.sequential_workflow import compile_sequence
        graph = decision_graph()
        graph.pop('id')
        self.assertFalse(compile_sequence(graph)['supported'])
        self.assertFalse(compile_graph(graph,allow_review=True)['supported'])
        self.assertFalse(compile_graph(graph,{'judge':'b'},allow_review=True,allow_decision=True)['supported'])
        self.assertTrue(compile_graph(graph,allow_review=True,allow_decision=True)['supported'])

    def test_pending_adapter_and_serving_drift_require_fresh_confirmation(self):
        from decision_fixtures import Harness
        from video_service.workflow_tickets import TicketConflict
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory, decision_graph())
            old = h.store.plan(h.ticket['id'], h.prefs)
            confirmed = h.store.confirm(h.ticket['id'], h.ticket['revision'], old['token'], True, h.prefs)
            h.store.adapter_profile = {**h.provider.descriptor, 'revision':'2'}
            with self.assertRaises(TicketConflict):
                h.store.run(h.ticket['id'], h.prefs, h.source, h.factory, request_id='stale-adapter', revision=confirmed['revision'], token=old['token'], operation='start')
            self.assertEqual(h.provider.calls, [])
            h.store.adapter_profile = dict(h.provider.descriptor)
            first = h.run()
            old = h.store.plan(first['id'], h.prefs)
            h.prefs = {**h.prefs, 'revision':1}
            with self.assertRaises(TicketConflict):
                h.store.confirm(first['id'], first['revision'], old['token'], False, h.prefs)
            h.store.adapter_profile = {**h.provider.descriptor, 'revision':'2'}
            h.provider.descriptor = h.store.adapter_profile
            second = h.run()
            self.assertEqual(second['status'], 'awaiting_review')
            self.assertEqual(second['decisions']['judge']['adapter']['revision'], '1')
            self.assertEqual(len(h.provider.calls), 1)

    def test_review_label_is_not_automatic_human_gate(self):
        from decision_fixtures import Harness, ControlledProvider
        graph = decision_graph()
        graph['nodes'] = [n for n in graph['nodes'] if n['id'] != 'gate']
        graph['nodes'][0]['options']['a_value'] = 'review'
        graph['edges'] = [e for e in graph['edges'] if e['target']['node'] != 'gate']
        for edge in graph['edges']:
            if edge['source']['node'] == 'gate':
                edge['source'] = {'node':'judge', 'port':'a'}
        with tempfile.TemporaryDirectory() as directory:
            h = Harness(directory, graph, ControlledProvider({'version':1,'label':'review','confidence':.8,'reason':'label only'}))
            self.assertEqual(h.run()['status'], 'awaiting_decision')
            final = h.run()
            self.assertEqual(final['status'], 'completed')
            self.assertEqual(final['reviews'], {})
            self.assertEqual(len(h.provider.calls), 1)

    def test_real_api_runtime_admission_two_phase_and_duplicate_reads(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import uuid4
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from video_service.workflow_definitions import DefinitionStore
        from decision_fixtures import Harness
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            h=Harness(root, decision_graph())
            asset_dir=root/'.assets'/('b'*32)
            asset_dir.mkdir(parents=True)
            (asset_dir/'source.mp4').write_bytes(h.source.read_bytes())
            (asset_dir/'asset.json').write_text(json.dumps({'asset_id':'b'*32,'owner_id':None,'source_filename':'source.mp4','original_filename':'controlled fixture.mp4','size_bytes':h.source.stat().st_size}))
            graph=decision_graph();graph.pop('id');graph['revision']=0
            DefinitionStore(root).save('a'*32,graph)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root,service_quota_bytes=10**9,min_free_space_bytes=0)), TestClient(app) as client:
                base='/api/settings/decision-tickets'
                self.assertFalse(client.get(base+'/runtime').json()['connected'])
                request={'request_id':str(uuid4()),'definition_id':'a'*32,'definition_revision':1,'asset_id':'b'*32,'options':{}}
                self.assertEqual(client.post(base,json=request,headers={'origin':'https://untrusted.invalid'}).status_code,403)
                created=client.post(base,json=request)
                self.assertEqual(created.status_code,201,created.text)
                url=base+'/'+created.json()['id']
                self.assertFalse(client.get(url+'/plan').json()['ready'])
                for namespace in ('workflow-tickets','graph-tickets','review-tickets'):
                    response=client.post('/api/settings/'+namespace,json={**request,'request_id':str(uuid4())})
                    self.assertEqual(response.status_code,422,response.text)
                app.state.decision_executor_factory=h.factory
                app.state.decision_adapter_descriptor=h.provider.descriptor
                plan=client.get(url+'/plan').json()
                self.assertEqual(plan['paid_roles'],['decision'])
                self.assertIn('judge',plan['unresolved_routes'])
                confirmed=client.post(url+'/confirm',json={'revision':created.json()['revision'],'token':plan['token'],'paid_confirmed':True})
                self.assertEqual(confirmed.status_code,200,confirmed.text)
                args={'request_id':str(uuid4()),'revision':confirmed.json()['revision'],'token':plan['token']}
                from approval_fixtures import approved_post
                response=approved_post(client,url+'/start',json=args)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['status'],'awaiting_decision')
                self.assertEqual(approved_post(client,url+'/start',json=args).json()['revision'],response.json()['revision'])
                self.assertEqual(client.get(url).json()['decisions'],response.json()['decisions'])
                self.assertEqual(len(h.provider.calls),1)
                next_plan=client.get(url+'/plan').json()
                self.assertNotEqual(next_plan['token'],plan['token'])
                self.assertNotIn('decision',next_plan['paid_roles'])
                self.assertEqual(client.post(url+'/continue',json={**args,'request_id':str(uuid4())}).status_code,409)

    def test_structured_decision_result_can_be_read_without_executable_instructions(self):
        from video_service.decision_adapter import invoke_decision
        from decision_fixtures import ControlledProvider
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'prior.json'
            source.write_text(json.dumps({'version':1,'kind':'decision_result','judgment':{'label':'reject'},'reason':'not executable'}))
            provider=ControlledProvider()
            report=invoke_decision(provider,{'type':'decision_result','bytes':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()},source,root/'new')
            self.assertEqual(provider.calls[0]['content']['judgment']['label'],'reject')
            self.assertEqual(report['judgment']['label'],'pass')

    def test_actual_cpu_selected_encode_uses_server_admitted_dynamic_plan(self):
        import subprocess, os, shutil
        from video_service.decision_tickets import DecisionTicketStore
        from media_worker.parallel_nodes import ParallelMediaExecutor
        from decision_fixtures import ControlledProvider
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'synthetic.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=10:d=0.4','-f','lavfi','-i','sine=frequency=440:duration=0.4','-shortest','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            provider=ControlledProvider()
            store=DecisionTicketStore(root,adapter_profile=provider.descriptor)
            graph=decision_graph()
            asset={'asset_id':'b'*32,'size_bytes':source.stat().st_size,'source_mtime_ns':source.stat().st_mtime_ns}
            ticket=store.create('actual-cpu',{'definition_id':graph['id'],'definition_revision':1,'asset_id':'b'*32,'options':{}},lambda:graph,lambda:asset)
            prefs={'revision':0,'api_keys':{}}
            def factory(bound,options,admitted):
                execute=ParallelMediaExecutor(bound,options,source,admitted)
                execute.decision_provider=provider
                return execute
            def run(number):
                current=store.get(ticket['id']);plan=store.plan(ticket['id'],prefs)
                confirmed=store.confirm(ticket['id'],current['revision'],plan['token'],bool(plan['paid_roles']),prefs)
                return store.run(ticket['id'],prefs,source,factory,request_id='cpu-'+str(number),revision=confirmed['revision'],token=plan['token'],operation='start' if number==0 else 'continue')
            first=run(0)
            self.assertEqual(first['status'],'awaiting_decision',first)
            self.assertEqual(run(1)['status'],'awaiting_review')
            doc=store.review_document(ticket['id'],'gate');view=doc.get()
            doc.approve(view['state_revision'],view['revision'],view['sha256'],view['target'],'explicit-cpu-review')
            final=run(2)
            self.assertEqual(final['status'],'completed',final)
            video=store.artifact_path(ticket['id'],'a','video')
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)]))
            self.assertGreater(float(probe['format']['duration']),0)
            self.assertEqual(len(provider.calls),1)
            self.assertEqual(final['decisions']['judge']['input_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            if os.getenv('WF06_CPU_EVIDENCE_DIR'):
                out=Path(os.environ['WF06_CPU_EVIDENCE_DIR']);out.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(video,out/'selected-a-synthetic.mp4')
                shutil.copyfile(store.artifact_path(ticket['id'],'joined','manifest'),out/'manifest.json')
                (out/'result.json').write_text(json.dumps({'mode':'actual synthetic CPU encode/probe; explicit structured adapter fixture, NOT external inference','result':final,'probe':probe,'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest()},ensure_ascii=False,indent=2))

    def test_passthrough_keeps_compact_proof_reference_not_recursive_report_copy(self):
        from decision_fixtures import Harness
        with tempfile.TemporaryDirectory() as directory:
            h=Harness(directory,decision_graph())
            h.run();second=h.run()
            proof=next(n for n in second['steps'] if n['id']=='judge')['artifacts']['a']['decision_provenance']
            self.assertEqual(set(proof),{'sha256','report_sha256','input_sha256','selected_port','adapter'})
            self.assertEqual(proof['report_sha256'],second['decisions']['judge']['report_sha256'])


if __name__ == '__main__':
    unittest.main()
