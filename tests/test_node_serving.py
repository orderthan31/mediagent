import json
import tempfile
import unittest
from pathlib import Path

from video_service.node_contracts import node_catalog, validate_node
from video_service.serving import serving_settings, save_serving
from video_service.llm_settings import LLMSettingsStore, SettingsConflict
from video_service.workflows import WorkflowTemplate, workflow_plan


class NodeServingTests(unittest.TestCase):
    def test_catalog_covers_real_fixed_template_stages(self):
        nodes = {n['id']: n for n in node_catalog()['nodes']}
        for template in WorkflowTemplate:
            plan = workflow_plan(template, subtitle_input=template == 'translate', subtitle_mode='none')
            self.assertTrue(set(plan['stages']) <= set(nodes))
        self.assertIn('faceswap', nodes)
        self.assertEqual(nodes['decision']['execution'], 'explicit_decision_ticket')
        self.assertEqual(nodes['decision']['worker_role'], 'control')
        self.assertEqual(nodes['decision']['outputs']['result'], 'decision_result')
        self.assertEqual(nodes['encode']['embedded_operations'], ['burn_subtitles'])
        self.assertFalse(node_catalog()['standalone_execution'])

    def test_typed_ports_validate_without_running_or_resolving_files(self):
        result = validate_node({'node': 'transcribe', 'inputs': {'audio': 'audio', 'timeline': 'timeline_map'}})
        self.assertEqual(result['outputs'], {'transcript': 'transcript'})
        self.assertEqual(result['scope'], 'port_types_and_options_only')
        for payload in [
            {'node': 'decision', 'inputs': {}},
            {'node': 'transcribe', 'inputs': {'audio': 'video', 'timeline': 'timeline_map'}},
            {'node': 'transcribe', 'inputs': {'audio': 'audio'}},
            {'node': 'analyze', 'inputs': {'video': 'video', 'extra': 'audio'}},
            {'node': 'encode', 'inputs': {'video': 'video'}, 'options': {'subtitle_mode': 'burn'}},
            {'node': 'encode', 'inputs': {'video': 'video'}, 'options': {'subtitle_mode': 'none', 'provider': 'x'}},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_node(payload)
        self.assertTrue(validate_node({'node': 'encode', 'inputs': {'video': 'video'}, 'options': {'subtitle_mode': 'none'}})['valid'])

    def test_store_reuses_worker_fields_and_preserves_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LLMSettingsStore(root)
            initial = store.public()
            fields = {k: initial[k] for k in ('revision', 'transcription_provider', 'translation_provider', 'transcription_fallback_provider', 'translation_fallback_provider', 'transcription_model', 'translation_model', 'transcription_fallback_model', 'translation_fallback_model', 'fallback_on_error', 'fallback_on_block')}
            fields['credential_updates'] = {'gemini': {'api_key': 'WF01FAKECREDENTIALNOTREAL000000000'}}
            store.update(None, fields)
            key = (root / '.llm-settings/master.key').read_bytes()
            encrypted = json.loads(store.path(None).read_text())['credentials']
            payload = {'revision': 1, 'workers': {'transcription': {'provider': 'openai', 'model': 'whisper-1', 'fallback_provider': 'gemini', 'fallback_model': 'gemini-fixture'}, 'translation': {'provider': 'gemini', 'model': 'gemini-fixture', 'fallback_provider': 'openai', 'fallback_model': ''}}, 'fallback_on_error': True, 'fallback_on_block': False}
            result = save_serving(root, None, payload)
            self.assertEqual(result['revision'], 2)
            self.assertEqual(serving_settings(root)['workers']['transcription']['model'], 'whisper-1')
            self.assertEqual(store.resolve()['transcription_provider'], 'openai')
            self.assertTrue(store.resolve()['fallback_on_error'])
            self.assertEqual((root / '.llm-settings/master.key').read_bytes(), key)
            self.assertEqual(json.loads(store.path(None).read_text())['credentials'], encrypted)
            self.assertNotIn('WF01FAKE', json.dumps(result))
            with self.assertRaises(SettingsConflict):
                save_serving(root, None, payload)
            payload['revision'] = 2
            payload['workers']['transcription']['provider'] = 'anthropic'
            with self.assertRaises(ValueError):
                save_serving(root, None, payload)
            self.assertEqual(store.public()['revision'], 2)
            payload['workers']['transcription']['provider'] = 'openai'
            payload['credential_updates'] = {}
            with self.assertRaises(ValueError):
                save_serving(root, None, payload)


class ServingAPITests(unittest.TestCase):
    def test_real_routes_revision_owner_origin_and_input_limits(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory, patch.object(settings_routes, 'settings', SimpleNamespace(storage_root=Path(directory))):
            app = FastAPI()
            app.state.auth = SimpleNamespace(store=None)
            app.state.cors_origins = ['http://testserver']
            app.include_router(settings_routes.router)
            with TestClient(app) as client:
                initial = client.get('/api/settings/serving').json()
                self.assertEqual(initial['revision'], 0)
                self.assertEqual(initial['workers']['translation']['connection'], 'unverified')
                workers = {role: {k: initial['workers'][role][k] for k in ('provider', 'model', 'fallback_provider', 'fallback_model')} for role in ('transcription', 'translation')}
                workers['transcription'].update(provider='openai', model='whisper-1')
                payload = dict(revision=0, workers=workers, fallback_on_error=False, fallback_on_block=False)
                saved = client.put('/api/settings/serving', json=payload)
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(client.get('/api/settings/llm').json()['transcription_model'], 'whisper-1')
                self.assertEqual(client.get('/api/settings/serving').json()['revision'], 1)
                self.assertEqual(client.put('/api/settings/serving', json=payload).status_code, 409)
                self.assertEqual(client.put('/api/settings/serving', json=payload, headers={'Origin': 'https://evil.invalid'}).status_code, 403)
                self.assertEqual(client.put('/api/settings/serving', content='x').status_code, 415)
                self.assertEqual(client.put('/api/settings/serving', content='x'*8193, headers={'Content-Type': 'application/json'}).status_code, 413)
                self.assertEqual(client.get('/api/settings/node-catalog').json()['standalone_execution'], False)
                self.assertEqual(client.post('/api/settings/node-validation', json={'node':'analyze','inputs':{'video':'audio'}}).status_code, 422)
                result = client.post('/api/settings/node-validation', json={'node':'analyze','inputs':{'video':'video'}})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['outputs'], {'metadata':'media_metadata'})

    def test_role_settings_reach_existing_provider_without_inference(self):
        from media_worker.providers import GeminiProvider
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = serving_settings(root)
            workers = {role: {k: initial['workers'][role][k] for k in ('provider','model','fallback_provider','fallback_model')} for role in ('transcription','translation')}
            workers['transcription'].update(provider='openai', model='whisper-1')
            save_serving(root, None, dict(revision=0, workers=workers, fallback_on_error=False, fallback_on_block=False))
            provider = GeminiProvider(LLMSettingsStore(root).resolve())
            self.assertEqual(provider.transcription_identity, 'openai:whisper-1')
