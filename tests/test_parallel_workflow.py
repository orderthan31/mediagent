"""WF-04 isolated scheduling primitives; no operating executor or queue."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest


def branching_graph():
    nodes = [
        {'id': 'choose', 'type': 'select', 'position': {'x': 340, 'y': 140}, 'options': {'data_type': 'video', 'selection': 'both'}},
        {'id': 'a', 'type': 'encode', 'position': {'x': 720, 'y': 40}, 'options': {'subtitle_mode': 'none'}},
        {'id': 'b', 'type': 'encode', 'position': {'x': 720, 'y': 360}, 'options': {'subtitle_mode': 'none'}},
        {'id': 'joined', 'type': 'join', 'position': {'x': 1100, 'y': 180}, 'options': {'left_type': 'video', 'right_type': 'video'}},
    ]
    endpoints = [('$input', 'video', 'choose', 'value'), ('choose', 'a', 'a', 'video'), ('choose', 'b', 'b', 'video'), ('a', 'video', 'joined', 'left'), ('b', 'video', 'joined', 'right')]
    return {'catalog_version': 1, 'revision': 1, 'name': '수동 분기·결과 목록', 'inputs': {'video': 'video'}, 'nodes': nodes,
            'edges': [{'id': str(i), 'source': {'node': a, 'port': ap}, 'target': {'node': b, 'port': bp}} for i, (a, ap, b, bp) in enumerate(endpoints)]}


class ParallelSchedulingTests(unittest.TestCase):
    def test_real_bounded_overlap_and_atomic_state_readback(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.parallel_scheduler'),
                             'Bounded independent-branch scheduler is missing')
        from video_service.parallel_scheduler import run_ready
        from video_service.storage import write_json_atomic, read_json
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        peak = 0
        threads = set()
        snapshots = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def execute(step):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                    threads.add(threading.get_ident())
                try:
                    if step['id'] in {'a', 'b'}:
                        barrier.wait(timeout=3)
                    output = root / (step['id'] + '.txt')
                    output.write_text(step['id'], encoding='utf-8')
                    return {'filename': output.name, 'bytes': output.stat().st_size}
                finally:
                    with lock:
                        active -= 1
            def publish(state):
                write_json_atomic(root / 'state.json', state)
                reread = read_json(root / 'state.json')
                self.assertEqual(reread, state)
                snapshots.append(reread)
            steps = [{'id': identity, 'dependencies': []} for identity in ('a', 'b', 'c')]
            result = run_ready(steps, execute, publish, max_workers=2)
            self.assertEqual(peak, 2)
            self.assertGreaterEqual(len(threads), 2)
            self.assertTrue(any(sum(n['status'] == 'running' for n in s['nodes'].values()) == 2 for s in snapshots))
            self.assertTrue(all(n['status'] == 'succeeded' for n in result['nodes'].values()))
            self.assertEqual(result['unresolved'], [])
            self.assertEqual(read_json(root / 'state.json'), result)
            self.assertEqual([p.read_text() for p in sorted(root.glob('*.txt'))], ['a', 'b', 'c'])
            self.assertEqual([s['revision'] for s in snapshots], list(range(1, len(snapshots) + 1)))

    def test_failed_branch_retains_partial_without_stopping_independent_success(self):
        from video_service import parallel_scheduler as scheduler
        self.assertTrue(hasattr(scheduler, 'NodeFailure'), 'Partial branch outcome is not preserved')
        barrier = threading.Barrier(2)
        failed = threading.Event()
        snapshots = []
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def execute(step):
                calls.append(step['id'])
                barrier.wait(timeout=3)
                if step['id'] == 'bad':
                    output = root / 'partial.json'
                    output.write_text('{"partial":true}')
                    failed.set()
                    raise scheduler.NodeFailure({'filename': output.name}, RuntimeError('private provider diagnostic'))
                self.assertTrue(failed.wait(timeout=3))
                output = root / 'success.txt'
                output.write_text('independent result')
                return {'filename': output.name}
            result = scheduler.run_ready([
                {'id': 'bad', 'dependencies': []},
                {'id': 'good', 'dependencies': []},
                {'id': 'after_bad', 'dependencies': ['bad']},
            ], execute, snapshots.append, max_workers=2)
            self.assertEqual(result['nodes']['bad'], {'status': 'failed', 'error_type': 'RuntimeError', 'partial': {'filename': 'partial.json'}})
            self.assertEqual(result['nodes']['good']['status'], 'succeeded')
            self.assertEqual(set(calls), {'bad', 'good'})
            self.assertEqual(result['unresolved'], ['after_bad'])
            self.assertEqual(result['nodes']['after_bad']['status'], 'pending')
            self.assertEqual((root / 'success.txt').read_text(), 'independent result')
            self.assertTrue(json.loads((root / 'partial.json').read_text())['partial'])
            self.assertNotIn('private provider diagnostic', json.dumps(snapshots))

    def test_invalid_dependency_graph_and_limits_have_no_side_effects(self):
        from video_service.parallel_scheduler import run_ready
        base = [{'id': 'a', 'dependencies': []}]
        invalid_steps = [
            [{'id': 'a', 'dependencies': []}, {'id': 'a', 'dependencies': []}],
            [{'id': 'a', 'dependencies': ['missing']}],
            [{'id': 'a', 'dependencies': ['b']}, {'id': 'b', 'dependencies': ['a']}],
            [{'id': '../escape', 'dependencies': []}],
            [{'id': 'a', 'dependencies': 'a'}],
            [{'id': 'a', 'dependencies': ['a']}],
            [{'id': str(i), 'dependencies': []} for i in range(101)],
        ]
        for workers in (0, -1, True, 5, 1.5, '2'):
            invalid_steps.append((base, workers))
        for case in invalid_steps:
            steps, workers = case if isinstance(case, tuple) else (case, 2)
            effects = []
            with self.subTest(steps=steps, workers=workers):
                with self.assertRaises(ValueError):
                    run_ready(steps, lambda s: effects.append('execute'), lambda s: effects.append('publish'), max_workers=workers)
                self.assertEqual(effects, [])

    def test_parallel_compiler_keeps_ports_options_and_shared_producer_once(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.parallel_workflow'),
                             'Definition-driven parallel admission is missing')
        import copy
        from test_sequential_workflow import graph
        from video_service.parallel_workflow import compile_parallel
        from video_service.sequential_workflow import compile_sequence
        definition = graph()
        other = copy.deepcopy(definition['nodes'][1])
        other['id'] = 'other_prepare'
        other['options']['audio_filter'] = 'off'
        definition['nodes'].append(other)
        definition['edges'].append({'id': 'other_edge', 'source': {'node': 'extract', 'port': 'audio'}, 'target': {'node': other['id'], 'port': 'audio'}})
        before = copy.deepcopy(definition)
        plan = compile_parallel(definition)
        self.assertTrue(plan['supported'], plan['reasons'])
        indexed = {step['id']: step for step in plan['steps']}
        self.assertEqual(set(indexed), {'extract', 'prepare', 'other_prepare'})
        self.assertEqual(indexed['extract']['dependencies'], [])
        self.assertEqual(indexed['prepare']['dependencies'], ['extract'])
        self.assertEqual(indexed['other_prepare']['bindings']['audio'], {'node': 'extract', 'port': 'audio'})
        self.assertEqual(indexed['prepare']['options']['audio_filter'], 'strong')
        self.assertEqual(indexed['other_prepare']['options']['audio_filter'], 'off')
        self.assertFalse(compile_sequence(definition)['supported'])
        self.assertEqual(definition, before)

    def test_real_cpu_parallel_encodes_have_isolated_node_contexts(self):
        self.assertIsNotNone(importlib.util.find_spec('media_agent.parallel_nodes'),
                             'Branch-isolated native node adapter is missing')
        import hashlib
        import subprocess
        from media_agent.parallel_nodes import ParallelMediaExecutor
        from video_service.parallel_workflow import compile_parallel
        from video_service.parallel_scheduler import run_ready
        from video_service.storage import write_json_atomic, read_json
        definition = {'catalog_version': 1, 'revision': 1, 'name': '합성 CPU 병렬', 'inputs': {'video': 'video'}, 'nodes': [], 'edges': []}
        for branch, quality in [('a', 'compact'), ('b', 'high')]:
            definition['nodes'].extend([
                {'id': 'encode_' + branch, 'type': 'encode', 'position': {'x': 0, 'y': 0}, 'options': {'subtitle_mode': 'none', 'quality_profile': quality}},
                {'id': 'verify_' + branch, 'type': 'validate_video', 'position': {'x': 200, 'y': 0}, 'options': {}},
            ])
            definition['edges'].extend([
                {'id': 'input_' + branch, 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'encode_' + branch, 'port': 'video'}},
                {'id': 'encoded_' + branch, 'source': {'node': 'encode_' + branch, 'port': 'video'}, 'target': {'node': 'verify_' + branch, 'port': 'video'}},
            ])
        plan = compile_parallel(definition)
        self.assertTrue(plan['supported'], plan['reasons'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-shortest', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            native = ParallelMediaExecutor({}, {'source_language': 'auto', 'target_language': 'ko'}, source, plan, provider_factory=object)
            values = {}
            barrier = threading.Barrier(2)
            active = 0
            peak = 0
            lock = threading.Lock()
            def publish(state):
                for identity, node in state['nodes'].items():
                    if node['status'] == 'succeeded':
                        for port, meta in node['result']['artifacts'].items():
                            values[(identity, port)] = meta
                write_json_atomic(root / 'state.json', state)
            def execute(step):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    if step['type'] == 'encode':
                        barrier.wait(timeout=3)
                    inputs = {}
                    for port, binding in step['bindings'].items():
                        if binding['node'] == '$input':
                            inputs[port] = source
                        else:
                            meta = values[(binding['node'], binding['port'])]
                            path = root / meta['path']
                            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), meta['sha256'])
                            inputs[port] = path
                    work = root / step['id']
                    work.mkdir()
                    outputs = native(step, inputs, work, lambda: None)
                    self.assertEqual(set(outputs), set(step['outputs']))
                    return {'artifacts': {port: {'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for port, path in outputs.items()}}
                finally:
                    with lock:
                        active -= 1
            result = run_ready(plan['steps'], execute, publish, max_workers=2)
            self.assertTrue(all(n['status'] == 'succeeded' for n in result['nodes'].values()), result)
            self.assertEqual(peak, 2)
            self.assertEqual(read_json(root / 'state.json'), result)
            for branch in ('a', 'b'):
                self.assertTrue(read_json(root / ('verify_' + branch) / 'validation.json')['valid'])
                self.assertGreater((root / ('encode_' + branch) / 'final.mp4').stat().st_size, 0)

    def test_control_ports_are_typed_and_manifest_is_not_a_media_file(self):
        import copy
        from video_service.workflow_graph import validate_graph
        from video_service.node_contracts import validate_node
        from video_service.sequential_workflow import compile_sequence
        definition = branching_graph()
        self.assertTrue(validate_graph(definition)['valid'], validate_graph(definition)['issues'])
        self.assertFalse(compile_sequence(definition)['supported'])
        result = validate_node({'node': 'select', 'inputs': {'value': 'audio'}, 'options': {'data_type': 'audio', 'selection': 'a'}})
        self.assertEqual(result['outputs'], {'a': 'audio', 'b': 'audio'})
        wrong = copy.deepcopy(definition)
        wrong['nodes'][3]['options']['left_type'] = 'audio'
        self.assertFalse(validate_graph(wrong)['valid'])
        wrong = copy.deepcopy(definition)
        wrong['edges'].append({'id': 'unsafe', 'source': {'node': 'joined', 'port': 'manifest'}, 'target': {'node': 'a', 'port': 'video'}})
        issues = validate_graph(wrong)['issues']
        self.assertTrue(any('유형' in issue['message'] for issue in issues))

    def test_graph_compiler_fixes_routing_and_preserves_native_origin(self):
        from video_service.parallel_workflow import compile_graph
        definition = branching_graph()
        plan = compile_graph(definition, {'choose': 'a'})
        self.assertTrue(plan['supported'], plan['reasons'])
        steps = {n['id']: n for n in plan['steps']}
        self.assertEqual(plan['choices'], {'choose': 'a'})
        self.assertTrue(steps['a']['selected'])
        self.assertFalse(steps['b']['selected'])
        self.assertEqual(steps['joined']['active_bindings'], {'left': {'node': 'a', 'port': 'video'}})
        self.assertEqual(steps['joined']['dependencies'], ['a'])
        self.assertEqual(steps['a']['bindings']['video'], {'node': 'choose', 'port': 'a'})
        self.assertEqual(steps['a']['native_bindings']['video'], {'node': '$input', 'port': 'video'})
        self.assertFalse(compile_graph(definition, {'missing': 'a'})['supported'])
        self.assertFalse(compile_graph(definition, {'choose': 'invalid'})['supported'])

    def test_approved_settlement_distinguishes_blocked_and_skipped(self):
        from video_service.parallel_scheduler import run_ready
        calls = []
        snapshots = []
        def execute(step):
            calls.append(step['id'])
            if step['id'] == 'a':
                raise RuntimeError('injected branch failure')
            return {'done': True}
        result = run_ready([
            {'id': 'a', 'dependencies': [], 'selected': True},
            {'id': 'b', 'dependencies': [], 'selected': True},
            {'id': 'joined', 'dependencies': ['a', 'b'], 'selected': True},
            {'id': 'off', 'dependencies': [], 'selected': False},
            {'id': 'empty_join', 'dependencies': ['off'], 'selected': False},
        ], execute, snapshots.append, settle=True)
        self.assertEqual(set(calls), {'a', 'b'})
        self.assertEqual(result['nodes']['b']['status'], 'succeeded')
        self.assertEqual(result['nodes']['joined']['status'], 'blocked')
        self.assertEqual(result['nodes']['joined']['blocked_by'], ['a'])
        self.assertEqual(result['nodes']['off']['status'], 'skipped')
        self.assertEqual(result['nodes']['empty_join']['status'], 'skipped')
        self.assertEqual(result['unresolved'], [])

    def test_graph_ticket_snapshot_confirmation_manifest_and_independent_failure(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.graph_tickets'), 'Persistent graph ticket orchestration missing')
        import copy
        from video_service.graph_tickets import GraphTicketStore
        from video_service.workflow_tickets import TicketConflict, TicketStore
        prefs = {'revision': 0, 'api_keys': {}, 'transcription_model': 'fixture'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.bin'
            source.write_bytes(b'isolated deterministic source')
            definition = branching_graph()
            definition['id'] = 'a' * 32
            asset = {'asset_id': 'b' * 32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            store = GraphTicketStore(root)
            identity = {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {'branch_choices': {'choose': 'a'}}}
            ticket = store.create('one', identity, lambda: definition, lambda: asset)
            self.assertEqual(ticket['status'], 'held')
            self.assertEqual(TicketStore(root).list(), [])
            definition['revision'] = 2
            self.assertEqual(store.get(ticket['id'])['definition']['revision'], 1)
            changed = copy.deepcopy(identity)
            changed['options']['branch_choices']['choose'] = 'both'
            with self.assertRaises(TicketConflict):
                store.create('one', changed, lambda: definition, lambda: asset)
            calls = []
            def factory(bound, options):
                self.assertEqual(bound['revision'], 0)
                def execute(step, inputs, work, check):
                    calls.append(step['id'])
                    output = work / 'same.mp4'
                    output.write_bytes(b'deterministic branch output')
                    return {'video': output}
                return execute
            preview = store.plan(ticket['id'], prefs)
            self.assertEqual(preview['choices'], {'choose': 'a'})
            store.confirm(ticket['id'], ticket['revision'], preview['token'], False, prefs)
            with self.assertRaises(TicketConflict):
                store.run(ticket['id'], {**prefs, 'revision': 1}, source, factory)
            result = store.run(ticket['id'], prefs, source, factory)
            self.assertEqual(result['status'], 'completed', result.get('error'))
            self.assertEqual(calls, ['a'])
            self.assertEqual(next(n for n in result['steps'] if n['id'] == 'b')['status'], 'skipped')
            manifest = json.loads(store.artifact_path(result['id'], 'joined', 'manifest').read_text())
            self.assertEqual(set(manifest['members']), {'a.video'})
            self.assertEqual(manifest['members']['a.video']['type'], 'video')
            self.assertNotIn(str(root), json.dumps(result))
            identity['definition_revision'] = 2
            identity['options']['branch_choices']['choose'] = 'both'
            other = store.create('two', identity, lambda: definition, lambda: asset)
            preview = store.plan(other['id'], prefs)
            store.confirm(other['id'], other['revision'], preview['token'], False, prefs)
            barrier = threading.Barrier(2)
            def failed_factory(bound, options):
                def execute(step, inputs, work, check):
                    barrier.wait(timeout=3)
                    if step['id'] == 'a':
                        (work / 'partial-result.json').write_text('{"partial":true}')
                        raise RuntimeError('private diagnostic')
                    output = work / 'same.mp4'
                    output.write_bytes(b'preserved independent output')
                    return {'video': output}
                return execute
            result = store.run(other['id'], prefs, source, failed_factory)
            steps = {n['id']: n for n in result['steps']}
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(steps['a']['status'], 'failed')
            self.assertTrue(steps['a']['partial_artifacts'])
            self.assertEqual(steps['b']['status'], 'succeeded')
            self.assertEqual(steps['joined']['status'], 'blocked')
            self.assertTrue(store.artifact_path(result['id'], 'b', 'video').is_file())
            self.assertEqual(store.get(result['id']), result)
            self.assertNotIn('private diagnostic', json.dumps(result))
            third = store.create('three', identity, lambda: definition, lambda: asset)
            preview = store.plan(third['id'], prefs)
            store.confirm(third['id'], third['revision'], preview['token'], False, prefs)
            result = store.run(third['id'], prefs, source, factory)
            self.assertEqual(result['status'], 'completed')
            manifest = json.loads(store.artifact_path(result['id'], 'joined', 'manifest').read_text())
            self.assertEqual(set(manifest['members']), {'a.video', 'b.video'})
            self.assertNotEqual(manifest['members']['a.video']['path'], manifest['members']['b.video']['path'])
            with self.assertRaises(FileNotFoundError):
                store.artifact_path(result['id'], 'choose', 'a')
            empty = copy.deepcopy(definition)
            empty['id'] = 'c'*32
            for edge in empty['edges']:
                if edge['target']['node'] == 'joined':
                    edge['source'] = {'node': 'b', 'port': 'video'}
            empty_identity = {**identity, 'definition_id': empty['id'], 'options': {'branch_choices': {'choose': 'a'}}}
            fourth = store.create('empty', empty_identity, lambda: empty, lambda: asset)
            preview = store.plan(fourth['id'], prefs)
            store.confirm(fourth['id'], fourth['revision'], preview['token'], False, prefs)
            result = store.run(fourth['id'], prefs, source, factory)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(next(n for n in result['steps'] if n['id'] == 'joined')['status'], 'skipped')

    def test_graph_api_held_runtime_confirmation_and_real_manifest_download(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import uuid4
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from video_service.workflow_definitions import DefinitionStore
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_dir = root / '.assets' / ('b' * 32)
            asset_dir.mkdir(parents=True)
            (asset_dir / 'source.mp4').write_bytes(b'isolated deterministic fixture')
            (asset_dir / 'asset.json').write_text(json.dumps({'asset_id': 'b' * 32, 'owner_id': None, 'source_filename': 'source.mp4', 'original_filename': 'fixture.mp4', 'size_bytes': (asset_dir / 'source.mp4').stat().st_size}))
            definition = branching_graph()
            definition['revision'] = 0
            DefinitionStore(root).save('a' * 32, definition)
            with patch.object(settings_routes, 'settings', SimpleNamespace(storage_root=root, service_quota_bytes=10**9, min_free_space_bytes=0)):
                app = FastAPI()
                app.state.auth = SimpleNamespace(store=None)
                app.state.cors_origins = ['http://testserver']
                app.include_router(settings_routes.router)
                with TestClient(app) as client:
                    base = '/api/settings/graph-tickets'
                    runtime = client.get(base + '/runtime')
                    self.assertEqual(runtime.status_code, 200, runtime.text)
                    self.assertFalse(runtime.json()['connected'])
                    payload = {'request_id': str(uuid4()), 'definition_id': 'a' * 32, 'definition_revision': 1, 'asset_id': 'b' * 32, 'options': {'branch_choices': {'choose': 'a'}}}
                    denied = client.post(base, json=payload, headers={'origin': 'https://untrusted.invalid'})
                    self.assertEqual(denied.status_code, 403)
                    response = client.post(base, json=payload)
                    self.assertEqual(response.status_code, 201, response.text)
                    ticket = response.json()
                    self.assertEqual(ticket['status'], 'held')
                    self.assertEqual(client.get('/api/settings/workflow-tickets').json()['tickets'], [])
                    preview = client.get(base + '/' + ticket['id'] + '/plan').json()
                    confirmed = client.post(base + '/' + ticket['id'] + '/confirm', json={'revision': ticket['revision'], 'token': preview['token'], 'paid_confirmed': False})
                    self.assertEqual(confirmed.status_code, 200, confirmed.text)
                    request = {'revision': confirmed.json()['revision'], 'token': preview['token']}
                    self.assertEqual(client.post(base + '/' + ticket['id'] + '/start', json=request).status_code, 409)
                    def factory(prefs, options):
                        def execute(step, inputs, work, check):
                            output = work / 'same.mp4'
                            output.write_bytes(b'deterministic output')
                            return {'video': output}
                        return execute
                    app.state.graph_executor_factory = factory
                    from approval_fixtures import approved_post
                    response = approved_post(client,base + '/' + ticket['id'] + '/start', json=request)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['status'], 'completed')
                    artifact = client.get(base + '/' + ticket['id'] + '/artifacts/joined/manifest')
                    self.assertEqual(artifact.status_code, 200, artifact.text)
                    self.assertEqual(set(artifact.json()['members']), {'a.video'})
                    self.assertEqual(client.get(base + '/' + ticket['id']).json()['status'], 'completed')

    def test_graph_ticket_real_cpu_native_join_preserves_both_output_names(self):
        import subprocess
        from video_service.graph_tickets import GraphTicketStore
        from media_agent.parallel_nodes import ParallelMediaExecutor
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10:d=0.4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.4', '-shortest', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            definition = branching_graph()
            definition['id'] = 'a' * 32
            definition['nodes'][3]['options'] = {'left_type': 'validation_report', 'right_type': 'validation_report'}
            for branch in ('a', 'b'):
                definition['nodes'].append({'id': 'verify_' + branch, 'type': 'validate_video', 'position': {'x': 900, 'y': 500}, 'options': {}})
                definition['edges'].append({'id': 'verify_' + branch, 'source': {'node': branch, 'port': 'video'}, 'target': {'node': 'verify_' + branch, 'port': 'video'}})
            for edge in definition['edges']:
                if edge['target']['node'] == 'joined':
                    edge['source'] = {'node': 'verify_' + edge['source']['node'], 'port': 'report'}
            asset = {'asset_id': 'b'*32, 'size_bytes': source.stat().st_size, 'source_mtime_ns': source.stat().st_mtime_ns}
            identity = {'definition_id': definition['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {'branch_choices': {'choose': 'both'}}}
            store = GraphTicketStore(root)
            ticket = store.create('native', identity, lambda: definition, lambda: asset)
            prefs = {'revision': 0, 'api_keys': {}}
            preview = store.plan(ticket['id'], prefs)
            store.confirm(ticket['id'], ticket['revision'], preview['token'], False, prefs)
            pair = threading.Barrier(2)
            def factory(bound, options):
                native = ParallelMediaExecutor(bound, options, source, ticket['sequence'], provider_factory=object)
                def execute(step, inputs, work, check):
                    if step['type'] == 'encode':
                        pair.wait(timeout=3)
                    return native(step, inputs, work, check)
                return execute
            result = store.run(ticket['id'], prefs, source, factory)
            self.assertEqual(result['status'], 'completed', result)
            manifest = json.loads(store.artifact_path(result['id'], 'joined', 'manifest').read_text())
            self.assertEqual(set(manifest['members']), {'verify_a.report', 'verify_b.report'})
            self.assertNotEqual(manifest['members']['verify_a.report']['path'], manifest['members']['verify_b.report']['path'])
            for branch in ('a', 'b'):
                self.assertTrue(json.loads(store.artifact_path(result['id'], 'verify_' + branch, 'report').read_text())['valid'])
                self.assertGreater(store.artifact_path(result['id'], branch, 'video').stat().st_size, 0)
            import os, shutil
            if os.getenv('WF04_CPU_EVIDENCE_DIR'):
                output = Path(os.environ['WF04_CPU_EVIDENCE_DIR'])
                output.mkdir(parents=True, exist_ok=True)
                for branch in ('a', 'b'):
                    shutil.copyfile(store.artifact_path(result['id'], branch, 'video'), output / ('synthetic-' + branch + '.mp4'))
                shutil.copyfile(store.artifact_path(result['id'], 'joined', 'manifest'), output / 'actual-manifest.json')
                (output / 'actual-ticket.json').write_text(json.dumps({'mode': 'Synthetic CPU FFmpeg, real graph store/scheduler/native adapters; no provider/GPU/user source', 'ticket': result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    unittest.main()
