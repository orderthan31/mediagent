"""WF-05 technical wait/continuation primitives; not a product policy approval."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class ReviewWaitTests(unittest.TestCase):
    def test_wait_persists_without_blocking_independent_branch(self):
        from video_service import parallel_scheduler as scheduler
        self.assertTrue(hasattr(scheduler, 'NodeWait'), 'Durable nonfailure wait outcome is missing')
        from video_service.storage import write_json_atomic, read_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def execute(step):
                calls.append(step['id'])
                if step['id'] == 'gate':
                    original = root / 'immutable-input.txt'
                    original.write_text('original bytes')
                    raise scheduler.NodeWait({'input_file': original.name, 'reason': 'explicit external decision required'})
                output = root / (step['id'] + '.txt')
                output.write_text('actual independent output')
                return {'file': output.name}
            result = scheduler.run_ready([
                {'id': 'gate', 'dependencies': []},
                {'id': 'after', 'dependencies': ['gate']},
                {'id': 'independent', 'dependencies': []},
            ], execute, lambda state: write_json_atomic(root / 'state.json', state), settle=True)
            self.assertEqual(set(calls), {'gate', 'independent'})
            self.assertEqual(result['nodes']['gate']['status'], 'waiting')
            self.assertEqual(result['nodes']['after']['status'], 'pending')
            self.assertEqual(result['nodes']['independent']['status'], 'succeeded')
            self.assertEqual(read_json(root / 'state.json'), result)
            self.assertEqual((root / 'immutable-input.txt').read_text(), 'original bytes')
            self.assertTrue((root / 'independent.txt').is_file())

    def test_immutable_review_revisions_and_approval_are_distinct(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.review_documents'), 'Immutable review document store missing')
        import hashlib
        from video_service.review_documents import ReviewDocuments
        from video_service.workflow_tickets import TicketConflict
        raw = json.dumps([{'start': 0, 'end': 1, 'text': 'original'}]).encode()
        meta = {'type': 'transcript', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'clock': {'basis': 'original'}}
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewDocuments(Path(directory) / 'review', {'ticket': 'a'*32, 'node': 'review-one'})
            initial = store.open(meta, raw, duration=4)
            self.assertEqual(initial['revision'], 1)
            self.assertTrue(initial['editable'])
            self.assertIsNone(initial['approval'])
            saved = store.save(initial['state_revision'], 1, initial['sha256'], initial['target'], [{'start': 0, 'end': 1.2, 'text': 'human corrected'}])
            self.assertEqual(saved['revision'], 2)
            self.assertIsNone(saved['approval'])
            self.assertEqual(store.version(1)['cues'][0]['text'], 'original')
            self.assertEqual(store.version(2)['cues'][0]['text'], 'human corrected')
            with self.assertRaises(TicketConflict):
                store.save(initial['state_revision'], 1, initial['sha256'], initial['target'], [])
            with self.assertRaises(TicketConflict):
                store.approve(saved['state_revision'], 2, saved['sha256'], '0'*64, 'wrong-target')
            approved = store.approve(saved['state_revision'], 2, saved['sha256'], saved['target'], 'approve-once')
            self.assertEqual(approved['approval']['revision'], 2)
            self.assertEqual(approved['approval']['sha256'], saved['sha256'])
            duplicate = store.approve(saved['state_revision'], 2, saved['sha256'], saved['target'], 'approve-once')
            self.assertEqual(approved, duplicate)
            with self.assertRaises(TicketConflict):
                store.save(approved['state_revision'], 2, approved['sha256'], approved['target'], approved['cues'])

    def test_request_changes_stays_waiting_and_stale_approval_is_rejected(self):
        from video_service.review_documents import ReviewDocuments
        from video_service.workflow_tickets import TicketConflict
        from video_service.review import BLOCKED_TEXT
        from media_worker.content_block import BLOCKED_TEXT as existing_marker
        self.assertEqual(BLOCKED_TEXT, existing_marker)
        import hashlib
        raw = json.dumps([{'start': 0, 'end': 1, 'text': BLOCKED_TEXT}]).encode()
        meta = {'type': 'transcript', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'clock': {'basis': 'original'}}
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewDocuments(Path(directory) / 'one', {'ticket': 'a'*32, 'node': 'gate'})
            initial = store.open(meta, raw, duration=4)
            with self.assertRaises(ValueError):
                store.approve(initial['state_revision'], 1, initial['sha256'], initial['target'], 'blocked')
            self.assertTrue(hasattr(store, 'request_changes'), 'Nonterminal request-changes decision missing')
            changed = store.request_changes(initial['state_revision'], 1, initial['sha256'], initial['target'], 'changes', '명시 수정 요청')
            self.assertEqual(changed['status'], 'changes_requested')
            self.assertIsNone(changed['approval'])
            self.assertEqual(changed['revision'], 1)
            self.assertEqual(store.request_changes(initial['state_revision'], 1, initial['sha256'], initial['target'], 'changes', '명시 수정 요청'), changed)
            with self.assertRaises(TicketConflict):
                store.approve(initial['state_revision'], 1, initial['sha256'], initial['target'], 'stale')
            saved = store.save(changed['state_revision'], 1, changed['sha256'], changed['target'], [{'start': 0, 'end': 1, 'text': '사람이 수정한 텍스트'}])
            approved = store.approve(saved['state_revision'], 2, saved['sha256'], saved['target'], 'approve-fixed')
            path, decision = store.approved_output()
            self.assertIn('사람이 수정한 텍스트', path.read_text())
            self.assertEqual(decision['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(approved['revision'], 2)
            self.assertIsNone(store.version(1)['approval'])

    def test_explicit_seed_continues_only_pending_work_not_success_or_failure(self):
        from video_service.parallel_scheduler import run_ready, NodeWait
        from video_service.storage import write_json_atomic, read_json
        steps = [{'id': 'gate', 'dependencies': []}, {'id': 'after', 'dependencies': ['gate']}, {'id': 'independent', 'dependencies': []}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def execute(step):
                calls.append(step['id'])
                if step['id'] == 'gate':
                    if not (root / 'approved.txt').exists():
                        raise NodeWait({'review': 'external fixture decision not yet supplied'})
                    return {'file': 'approved.txt'}
                if step['id'] == 'after':
                    self.assertEqual((root / 'approved.txt').read_text(), 'approved exact bytes')
                (root / (step['id'] + '.txt')).write_text('actual output')
                return {'file': step['id'] + '.txt'}
            publish = lambda state: write_json_atomic(root / 'state.json', state)
            first = run_ready(steps, execute, publish, settle=True)
            source_seed = read_json(root / 'state.json')
            (root / 'approved.txt').write_text('approved exact bytes')
            source_seed['nodes']['gate'] = {'status': 'pending'}
            try:
                second = run_ready(steps, execute, publish, settle=True, initial=source_seed)
            except TypeError as exc:
                self.fail('Explicit persisted continuation is missing: ' + str(exc))
            self.assertTrue(all(n['status'] == 'succeeded' for n in second['nodes'].values()))
            self.assertEqual(calls.count('independent'), 1)
            self.assertEqual(calls.count('after'), 1)
            self.assertGreater(second['revision'], first['revision'])
            self.assertEqual(source_seed['nodes']['gate']['status'], 'pending')
            self.assertEqual(read_json(root / 'state.json'), second)
            invalid = json.loads(json.dumps(second))
            invalid['nodes']['gate']['status'] = 'running'
            effects = []
            with self.assertRaises(ValueError):
                run_ready(steps, lambda s: effects.append('execute'), lambda s: effects.append('publish'), initial=invalid)
            self.assertEqual(effects, [])

    def test_review_placement_has_typed_passthrough_and_separate_ticket_admission(self):
        from test_sequential_workflow import graph
        from video_service.parallel_workflow import compile_graph
        definition = graph()
        definition['nodes'].extend([
            {'id': 'before', 'type': 'review', 'position': {'x': 0, 'y': 0}, 'options': {'data_type': 'video'}},
            {'id': 'after', 'type': 'review', 'position': {'x': 0, 'y': 300}, 'options': {'data_type': 'audio'}},
        ])
        definition['edges'][0]['source'] = {'node': 'before', 'port': 'value'}
        definition['edges'].extend([
            {'id': 'review-input', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'before', 'port': 'value'}},
            {'id': 'review-output', 'source': {'node': 'prepare', 'port': 'audio'}, 'target': {'node': 'after', 'port': 'value'}},
        ])
        try:
            plan = compile_graph(definition, allow_review=True)
        except TypeError as exc:
            self.fail('Review-specific admission missing: ' + str(exc))
        self.assertTrue(plan['supported'], plan['reasons'])
        indexed = {n['id']: n for n in plan['steps']}
        self.assertEqual(indexed['extract']['bindings']['video'], {'node': 'before', 'port': 'value'})
        self.assertEqual(indexed['extract']['native_bindings']['video'], {'node': '$input', 'port': 'video'})
        self.assertEqual(indexed['after']['outputs'], {'value': 'audio'})
        self.assertFalse(compile_graph(definition)['supported'])

    def test_review_ticket_two_positions_explicit_continuation_and_drift(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.review_tickets'), 'Review-aware ticket runtime missing')
        from test_sequential_workflow import graph
        from video_service.review_tickets import ReviewTicketStore
        from video_service.workflow_tickets import TicketConflict
        definition = graph()
        definition.update(id='a'*32)
        definition['nodes'].extend([
            {'id': 'before', 'type': 'review', 'position': {'x': 0, 'y': 0}, 'options': {'data_type': 'video'}},
            {'id': 'after', 'type': 'review', 'position': {'x': 0, 'y': 300}, 'options': {'data_type': 'audio'}},
            {'id': 'independent', 'type': 'analyze', 'position': {'x': 300, 'y': 300}, 'options': {}},
            {'id': 'join', 'type': 'join', 'position': {'x': 600, 'y': 300}, 'options': {'left_type': 'audio', 'right_type': 'media_metadata'}},
        ])
        definition['edges'][0]['source'] = {'node': 'before', 'port': 'value'}
        for i, (a, ap, b, bp) in enumerate([('$input', 'video', 'before', 'value'), ('prepare', 'audio', 'after', 'value'), ('$input', 'video', 'independent', 'video'), ('after', 'value', 'join', 'left'), ('independent', 'metadata', 'join', 'right')]):
            definition['edges'].append({'id': 'extra-' + str(i), 'source': {'node': a, 'port': ap}, 'target': {'node': b, 'port': bp}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.bin'
            source.write_bytes(b'isolated input')
            asset = {'asset_id': 'b'*32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            store = ReviewTicketStore(root)
            ticket = store.create('new', {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {'branch_choices': {}}}, lambda: definition, lambda: asset)
            prefs = {'revision': 0, 'api_keys': {}}
            calls = []
            def factory(bound, options):
                def execute(step, inputs, work, check):
                    calls.append((step['id'], bound['revision']))
                    outputs = {}
                    for port in step['outputs']:
                        output = work / (port + '.json')
                        output.write_text(json.dumps({'fixture': True, 'node': step['id']}))
                        outputs[port] = output
                    return outputs
                return execute
            def confirm(preferences):
                current = store.get(ticket['id'])
                plan = store.plan(ticket['id'], preferences)
                confirmed = store.confirm(ticket['id'], current['revision'], plan['token'], False, preferences)
                return confirmed, plan
            def approve(node):
                doc = store.review_document(ticket['id'], node)
                current = doc.get()
                return doc.approve(current['state_revision'], current['revision'], current['sha256'], current['target'], 'approve-' + node)
            confirmed, plan = confirm(prefs)
            first = store.run(ticket['id'], prefs, source, factory, request_id='run-first', revision=confirmed['revision'], token=plan['token'], operation='start')
            self.assertEqual(first['status'], 'awaiting_review', first)
            self.assertEqual(calls, [('independent', 0)])
            self.assertEqual(next(n for n in first['steps'] if n['id'] == 'join')['status'], 'pending')
            self.assertFalse(store.review_document(ticket['id'], 'before').get()['editable'])
            approve('before')
            confirmed, plan = confirm(prefs)
            with self.assertRaises(TicketConflict):
                store.run(ticket['id'], {**prefs, 'revision': 1}, source, factory, request_id='drift', revision=confirmed['revision'], token=plan['token'], operation='continue')
            prefs = {**prefs, 'revision': 1}
            confirmed, plan = confirm(prefs)
            second = store.run(ticket['id'], prefs, source, factory, request_id='run-second', revision=confirmed['revision'], token=plan['token'], operation='continue')
            self.assertEqual(second['status'], 'awaiting_review', second)
            self.assertEqual(calls, [('independent', 0), ('extract', 1), ('prepare', 1)])
            self.assertEqual(next(n for n in second['steps'] if n['id'] == 'independent')['serving_snapshot']['revision'], 0)
            self.assertFalse(store.review_document(ticket['id'], 'after').get()['editable'])
            approve('after')
            confirmed, plan = confirm(prefs)
            final = store.run(ticket['id'], prefs, source, factory, request_id='run-third', revision=confirmed['revision'], token=plan['token'], operation='continue')
            self.assertEqual(final['status'], 'completed', final)
            replay = store.run(ticket['id'], prefs, source, factory, request_id='run-third', revision=confirmed['revision'], token=plan['token'], operation='continue')
            self.assertEqual(final, replay)
            self.assertEqual(calls, [('independent', 0), ('extract', 1), ('prepare', 1)])
            manifest = json.loads(store.artifact_path(ticket['id'], 'join', 'manifest').read_text())
            self.assertEqual(set(manifest['members']), {'after.value', 'independent.metadata'})

    def test_review_api_separate_admission_durable_wait_and_exact_approval(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import uuid4
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from video_service.workflow_definitions import DefinitionStore
        from app.api import settings_routes
        definition = {'catalog_version': 1, 'revision': 0, 'name': 'Actual isolated review API', 'inputs': {'video': 'video'},
                      'nodes': [{'id': 'gate', 'type': 'review', 'options': {'data_type': 'video'}, 'position': {'x': 0, 'y': 0}},
                                {'id': 'encode', 'type': 'encode', 'options': {'subtitle_mode': 'none'}, 'position': {'x': 300, 'y': 0}}],
                      'edges': [{'id': 'source', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'gate', 'port': 'value'}},
                                {'id': 'after', 'source': {'node': 'gate', 'port': 'value'}, 'target': {'node': 'encode', 'port': 'video'}}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / '.assets' / ('b'*32)
            assets.mkdir(parents=True)
            source = assets / 'source.mp4'
            source.write_bytes(b'explicit isolated fixture, no real user input')
            (assets / 'asset.json').write_text(json.dumps({'asset_id': 'b'*32, 'owner_id': None, 'source_filename': 'source.mp4', 'original_filename': 'fixture.mp4', 'size_bytes': source.stat().st_size}))
            from video_service.workflow_graph import validate_graph
            checked = validate_graph(definition)
            self.assertTrue(checked['valid'], checked['issues'])
            DefinitionStore(root).save('a'*32, definition)
            with patch.object(settings_routes, 'settings', SimpleNamespace(storage_root=root, service_quota_bytes=10**9, min_free_space_bytes=0)):
                app = FastAPI()
                app.state.auth = SimpleNamespace(store=None)
                app.state.cors_origins = ['http://testserver']
                app.include_router(settings_routes.router)
                calls = []
                def factory(bound, options):
                    def execute(step, inputs, work, check):
                        calls.append(step['id'])
                        output = work / 'fixture.mp4'
                        output.write_bytes(b'actual deterministic fixture output')
                        return {'video': output}
                    return execute
                with TestClient(app) as client:
                    base = '/api/settings/review-tickets'
                    response = client.get(base + '/runtime')
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertFalse(response.json()['connected'])
                    create = {'request_id': str(uuid4()), 'definition_id': 'a'*32, 'definition_revision': 1, 'asset_id': 'b'*32, 'options': {}}
                    self.assertEqual(client.post(base, json=create, headers={'origin': 'https://untrusted.invalid'}).status_code, 403)
                    ticket = client.post(base, json=create)
                    self.assertEqual(ticket.status_code, 201, ticket.text)
                    url = base + '/' + ticket.json()['id']
                    for old in ('graph-tickets', 'workflow-tickets'):
                        self.assertEqual(client.get('/api/settings/' + old).json()['tickets'], [])
                    def confirm():
                        current = client.get(url).json()
                        p = client.get(url + '/plan').json()
                        confirmed = client.post(url + '/confirm', json={'revision': current['revision'], 'token': p['token'], 'paid_confirmed': False})
                        self.assertEqual(confirmed.status_code, 200, confirmed.text)
                        return {'request_id': str(uuid4()), 'revision': confirmed.json()['revision'], 'token': p['token']}
                    start = confirm()
                    self.assertEqual(client.post(url + '/start', json=start).status_code, 409)
                    app.state.review_executor_factory = factory
                    from approval_fixtures import approved_post
                    first = approved_post(client,url + '/start', json=start)
                    self.assertEqual(first.status_code, 200, first.text)
                    self.assertEqual(first.json()['status'], 'awaiting_review')
                    self.assertEqual(calls, [])
                    review_url = url + '/reviews/gate'
                    view = client.get(review_url)
                    self.assertEqual(view.status_code, 200, view.text)
                    doc = view.json()
                    self.assertFalse(doc['editable'])
                    actual_input = client.get(review_url + '/input')
                    self.assertEqual(actual_input.status_code, 200, actual_input.text)
                    self.assertEqual(actual_input.content, source.read_bytes())
                    self.assertEqual(client.get(review_url + '/revisions/1').json()['sha256'], doc['sha256'])
                    action = {k: doc[k] for k in ('target', 'state_revision', 'revision', 'sha256')}
                    action.update(request_id=str(uuid4()), action='approve')
                    import threading
                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
                    from app.api import review_ticket_routes as review_routes
                    reached, release = threading.Event(), threading.Event()
                    original_verifier = review_routes.verified_document
                    def blocking_verifier(*args):
                        reached.set()
                        if not release.wait(5):
                            raise RuntimeError('Observer did not release isolated hash verifier')
                        return original_verifier(*args)
                    with patch.object(review_routes, 'verified_document', blocking_verifier), ThreadPoolExecutor(max_workers=2) as pool:
                        approving = pool.submit(client.post, review_url + '/decision', json={**action, 'target': '0'*64})
                        self.assertTrue(reached.wait(3))
                        reading = pool.submit(client.get, base + '/runtime')
                        try:
                            try:
                                self.assertEqual(reading.result(timeout=.8).status_code, 200)
                            except FutureTimeout:
                                self.fail('Review verification blocks the API event loop/progress reads')
                        finally:
                            release.set()
                            approving.result(timeout=5)
                    before_stat = source.stat()
                    before_bytes = source.read_bytes()
                    source.write_bytes(b'x' * len(before_bytes))
                    tampered = client.post(review_url + '/decision', json=action)
                    self.assertEqual(tampered.status_code, 409, tampered.text)
                    source.write_bytes(before_bytes)
                    import os
                    os.utime(source, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
                    rejected = client.post(review_url + '/decision', json={**action, 'target': '0'*64})
                    self.assertEqual(rejected.status_code, 409, rejected.text)
                    approved = client.post(review_url + '/decision', json=action)
                    self.assertEqual(approved.status_code, 200, approved.text)
                    self.assertEqual(client.post(review_url + '/decision', json=action).json(), approved.json())
                    self.assertEqual(client.get(url).json()['status'], 'awaiting_review')
                    self.assertEqual(calls, [])
                    continuation = confirm()
                    final = approved_post(client,url + '/continue', json=continuation)
                    self.assertEqual(final.status_code, 200, final.text)
                    self.assertEqual(final.json()['status'], 'completed', final.text)
                    self.assertEqual(approved_post(client,url + '/continue', json=continuation).json(), final.json())
                    self.assertEqual(calls, ['encode'])
                    download = client.get(url + '/artifacts/encode/video')
                    self.assertEqual(download.content, b'actual deterministic fixture output')

    def test_approved_text_bytes_reach_subtitle_and_second_review_without_repeating_stt(self):
        from review_fixtures import review_graph
        from video_service.review_tickets import ReviewTicketStore
        from video_service.review import BLOCKED_TEXT
        from video_service.subtitles import segments_to_srt
        from video_service.transcript import TranscriptSegment
        definition = review_graph()
        definition['id'] = 'a'*32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.bin'
            source.write_bytes(b'isolated deterministic fixture')
            asset = {'asset_id': 'b'*32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            store = ReviewTicketStore(root)
            ticket = store.create('text', {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {}}, lambda: definition, lambda: asset)
            prefs = {'revision': 0, 'api_keys': {}}
            calls = []
            received = []
            def factory(bound, options):
                def execute(step, inputs, work, check):
                    calls.append(step['id'])
                    outputs = {}
                    for port in step['outputs']:
                        output = work / (port + ('.srt' if port == 'subtitles' else '.json'))
                        if step['type'] == 'transcribe':
                            output.write_text(json.dumps([{'start': 0, 'end': .2, 'text': BLOCKED_TEXT}], ensure_ascii=False))
                        elif step['type'] == 'generate_subtitle':
                            cues = json.loads(inputs['transcript'].read_text())
                            received.append(cues)
                            output.write_text(segments_to_srt([TranscriptSegment.from_dict(c) for c in cues]))
                        else:
                            output.write_text(json.dumps({'isolated_fixture': True, 'node': step['id']}))
                        outputs[port] = output
                    return outputs
                execute.review_duration = .4
                return execute
            def run(i):
                current = store.get(ticket['id'])
                plan = store.plan(ticket['id'], prefs)
                confirmed = store.confirm(ticket['id'], current['revision'], plan['token'], bool(plan['paid_roles']), prefs)
                return store.run(ticket['id'], prefs, source, factory, request_id='phase-' + str(i), revision=confirmed['revision'], token=plan['token'], operation='start' if i == 0 else 'continue')
            first = run(0)
            self.assertEqual(first['status'], 'awaiting_review', first)
            self.assertNotIn('subtitle', calls)
            doc = store.review_document(ticket['id'], 'review_text')
            original = doc.get()
            with self.assertRaises(ValueError):
                doc.approve(original['state_revision'], 1, original['sha256'], original['target'], 'blocked')
            fixed = doc.save(original['state_revision'], 1, original['sha256'], original['target'], [{'start': .01, 'end': .3, 'text': 'human approved exact text'}])
            self.assertNotIn('subtitle', calls)
            doc.approve(fixed['state_revision'], fixed['revision'], fixed['sha256'], fixed['target'], 'fixed')
            metadata = store.review_document(ticket['id'], 'review_metadata')
            m = metadata.get()
            metadata.approve(m['state_revision'], m['revision'], m['sha256'], m['target'], 'metadata')
            second = run(1)
            self.assertEqual(second['status'], 'awaiting_review', second)
            self.assertEqual(received, [[{'start': .01, 'end': .3, 'text': 'human approved exact text'}]])
            self.assertNotIn('encode', calls)
            subtitle = store.review_document(ticket['id'], 'review_srt')
            s = subtitle.get()
            self.assertTrue(s['editable'])
            subtitle.approve(s['state_revision'], s['revision'], s['sha256'], s['target'], 'subtitles')
            final = run(2)
            self.assertEqual(final['status'], 'completed', final)
            self.assertEqual(calls.count('stt'), 1)
            self.assertEqual(calls.count('independent'), 1)
            self.assertEqual(calls.count('encode'), 1)

    def test_actual_cpu_media_uses_reviewed_bytes_and_preserves_old_phase(self):
        import subprocess, os, shutil, hashlib
        from review_fixtures import review_graph
        from video_service.review_tickets import ReviewTicketStore
        from media_worker.parallel_nodes import ParallelMediaExecutor
        from video_service.transcript import TranscriptSegment
        from video_service.review import BLOCKED_TEXT
        definition = review_graph()
        definition['id'] = 'a'*32
        definition['nodes'].append({'id': 'validate', 'type': 'validate_video', 'options': {}, 'position': {'x': 950, 'y': 500}})
        next(n for n in definition['nodes'] if n['id'] == 'joined')['options']['left_type'] = 'validation_report'
        for edge in definition['edges']:
            if edge['target'] == {'node': 'joined', 'port': 'left'}:
                edge['source'] = {'node': 'validate', 'port': 'report'}
        definition['edges'].append({'id': 'validate', 'source': {'node': 'encode', 'port': 'video'}, 'target': {'node': 'validate', 'port': 'video'}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-shortest', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            asset = {'asset_id': 'b'*32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            provider_calls = []
            class FixtureProvider:
                transcription_identity = 'explicit-offline-review-fixture'
                def transcribe(self, *args, **kwargs):
                    provider_calls.append('transcribe')
                    return [TranscriptSegment(0, .15, BLOCKED_TEXT)]
            store = ReviewTicketStore(root)
            ticket = store.create('cpu', {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {'source_language': 'en', 'target_language': 'en'}}, lambda: definition, lambda: asset)
            prefs = {'revision': 0, 'api_keys': {}}
            def run(phase):
                current = store.get(ticket['id'])
                p = store.plan(ticket['id'], prefs)
                current = store.confirm(ticket['id'], current['revision'], p['token'], bool(p['paid_roles']), prefs)
                return store.run(ticket['id'], prefs, source, lambda bound, opts: ParallelMediaExecutor(bound, opts, source, ticket['sequence'], provider_factory=FixtureProvider, paid_allowed=True), request_id='cpu-' + str(phase), revision=current['revision'], token=p['token'], operation='start' if phase == 0 else 'continue')
            first = run(0)
            self.assertEqual(first['status'], 'awaiting_review', first)
            doc = store.review_document(ticket['id'], 'review_text')
            original = doc.get()
            self.assertTrue(original['editable'])
            edited = doc.save(original['state_revision'], 1, original['sha256'], original['target'], [{'start': 0, 'end': .3, 'text': 'CPU manual accepted'}])
            doc.approve(edited['state_revision'], edited['revision'], edited['sha256'], edited['target'], 'cpu-text')
            mdoc = store.review_document(ticket['id'], 'review_metadata')
            m = mdoc.get()
            mdoc.approve(m['state_revision'], m['revision'], m['sha256'], m['target'], 'cpu-metadata')
            prefs = {**prefs, 'revision': 1}
            second = run(1)
            self.assertEqual(second['status'], 'awaiting_review', second)
            subtitle = store.review_document(ticket['id'], 'review_srt')
            s = subtitle.get()
            self.assertIn('CPU manual accepted', s['cues'][0]['text'])
            subtitle.approve(s['state_revision'], s['revision'], s['sha256'], s['target'], 'cpu-srt')
            result = run(2)
            self.assertEqual(result['status'], 'completed', result)
            report = json.loads(store.artifact_path(ticket['id'], 'validate', 'report').read_text())
            self.assertTrue(report['valid'])
            self.assertEqual(provider_calls, ['transcribe'])
            self.assertEqual(next(n for n in result['steps'] if n['id'] == 'stt')['serving_snapshot']['revision'], 0)
            self.assertEqual(next(n for n in result['steps'] if n['id'] == 'encode')['serving_snapshot']['revision'], 1)
            video = store.artifact_path(ticket['id'], 'encode', 'video')
            self.assertGreater(video.stat().st_size, 0)
            srt_path, approved = subtitle.approved_output()
            self.assertEqual(hashlib.sha256(srt_path.read_bytes()).hexdigest(), approved['sha256'])
            if os.getenv('WF05_CPU_EVIDENCE_DIR'):
                output = Path(os.environ['WF05_CPU_EVIDENCE_DIR'])
                output.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(video, output / 'synthetic-reviewed.mp4')
                shutil.copyfile(srt_path, output / 'approved.srt')
                shutil.copyfile(store.artifact_path(ticket['id'], 'joined', 'manifest'), output / 'actual-manifest.json')
                (output / 'actual-result.json').write_text(json.dumps({'mode': 'Actual CPU FFmpeg/probe/validation and durable review gates; transcription explicit offline fixture; no user input/GPU/provider/network', 'result': result, 'report': report, 'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2))

    def test_unsupported_clock_and_unknown_duration_are_read_only(self):
        import hashlib
        from video_service.review_documents import ReviewDocuments
        content = json.dumps([{'start': 0, 'end': .2, 'text': 'original'}]).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, clock, duration in [('packed', 'packed', .4), ('missing', 'original', None)]:
                doc = ReviewDocuments(root / name, {'ticket': 'a'*32, 'node': name})
                original = doc.open({'type': 'transcript', 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'clock': {'basis': clock}}, content, duration=duration)
                self.assertFalse(original['editable'], name)
                self.assertTrue(original['read_only_reason'])
                with self.assertRaises(ValueError):
                    doc.save(original['state_revision'], 1, original['sha256'], original['target'], original['cues'])
                self.assertEqual(doc.get(), original)


if __name__ == '__main__':
    unittest.main()
