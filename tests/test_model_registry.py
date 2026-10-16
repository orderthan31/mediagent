import importlib.util
import tempfile
import unittest
from pathlib import Path


class ModelRegistryTests(unittest.TestCase):
    def test_owner_immutable_revisions_and_separate_current_availability(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.model_registry'), 'Real registered model store missing')
        from video_service.model_registry import ModelRegistry, ModelConflict, ModelUnavailable
        with tempfile.TemporaryDirectory() as directory:
            registry=ModelRegistry(Path(directory),'owner-a')
            first=registry.save('a'*32,{'revision':0,'name':'Text model','provider':'openai','model':'gpt-4o-mini','uses':['translation','decision']})
            self.assertEqual(first['current_revision'],1)
            pinned=registry.resolve({'model_id':'a'*32,'revision':1},'translate')
            self.assertEqual(pinned['model'],'gpt-4o-mini')
            second=registry.save('a'*32,{'revision':first['revision'],'name':'New text model','provider':'openai','model':'gpt-4o','uses':['translation','decision']})
            self.assertEqual(second['current_revision'],2)
            self.assertEqual(registry.resolve({'model_id':'a'*32,'revision':1},'translate'),pinned)
            with self.assertRaises(ModelConflict):
                registry.save('a'*32,{'revision':first['revision'],'name':'stale','provider':'openai','model':'gpt-4o','uses':['translation']})
            with self.assertRaises(FileNotFoundError):
                ModelRegistry(directory,'owner-b').resolve({'model_id':'a'*32,'revision':1},'translate')
            with self.assertRaises(ValueError):
                registry.resolve({'model_id':'a'*32,'revision':1},'encode')
            stopped=registry.set_active('a'*32,second['revision'],False)
            self.assertFalse(stopped['active'])
            with self.assertRaises(ModelUnavailable):
                registry.resolve({'model_id':'a'*32,'revision':1},'translate')
            self.assertEqual(registry.resolve({'model_id':'a'*32,'revision':1},'translate',require_active=False),pinned)
            self.assertEqual(stopped['versions']['1']['model'],'gpt-4o-mini')

    def test_incompatible_use_and_credential_payload_are_rejected(self):
        from video_service.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as directory:
            registry=ModelRegistry(directory)
            for provider,model,uses in [('anthropic','claude-test',['transcription']),('openai','whisper-1',['translation']),('xai','grok-voice-transcribe-2.0',['decision']),('unknown','something',['translation'])]:
                with self.subTest(provider=provider,model=model),self.assertRaises(ValueError):
                    registry.save('a'*32,{'revision':0,'name':'incompatible','provider':provider,'model':model,'uses':uses})
            with self.assertRaises(ValueError):
                registry.save('b'*32,{'revision':0,'name':'no keys here','provider':'openai','model':'gpt-4o-mini','uses':['translation'],'api_key':None})

    def test_bound_definition_roundtrip_rejects_legacy_ticket_admission(self):
        from video_service.model_registry import ModelRegistry,ModelUnavailable
        from video_service.workflow_definitions import DefinitionStore
        from video_service.parallel_workflow import compile_graph
        from test_workflow_decision import decision_graph
        with tempfile.TemporaryDirectory() as directory:
            registry=ModelRegistry(directory)
            row=registry.save('c'*32,{'revision':0,'name':'Decision model','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
            graph=decision_graph();graph.pop('id');graph['revision']=0
            graph['nodes'][0]['model_ref']={'model_id':'c'*32,'revision':1}
            saved=DefinitionStore(directory).save('a'*32,graph)
            self.assertEqual(DefinitionStore(directory).get('a'*32)['nodes'][0]['model_ref'],graph['nodes'][0]['model_ref'])
            payload={k:saved[k] for k in ('catalog_version','revision','name','inputs','nodes','edges')}
            self.assertFalse(compile_graph(payload,allow_review=True,allow_decision=True)['supported'])
            registry.set_active('c'*32,row['revision'],False)
            self.assertEqual(DefinitionStore(directory).get('a'*32)['revision'],1)
            with self.assertRaises(ModelUnavailable):
                DefinitionStore(directory).save('b'*32,graph)

    def test_registry_api_crud_has_no_key_field_and_enforces_cas(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory:
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=Path(directory),service_quota_bytes=10**9,min_free_space_bytes=0)),TestClient(app) as client:
                url='/api/settings/registered-models/'+'a'*32
                response=client.put(url,json={'revision':0,'name':'registered','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['connection'],'unverified')
                self.assertEqual(client.get('/api/settings/registered-models').json()['models'][0]['id'],'a'*32)
                self.assertEqual(client.put(url,json={'revision':0,'name':'stale','provider':'openai','model':'gpt-4o-mini','uses':['decision']}).status_code,409)
                state=client.post(url+'/availability',json={'revision':response.json()['revision'],'active':False})
                self.assertEqual(state.status_code,200,state.text)
                self.assertFalse(client.get(url).json()['active'])
                self.assertEqual(client.put(url,json={'revision':state.json()['revision'],'name':'keys forbidden','provider':'openai','model':'gpt-4o-mini','uses':['decision'],'api_key':None}).status_code,422)

    def test_entity_internal_revision_and_model_id_cannot_disagree_with_reference(self):
        from video_service.model_registry import ModelRegistry,ModelConflict
        from video_service.workflow_tickets import digest
        from video_service.storage import write_json_atomic
        with tempfile.TemporaryDirectory() as directory:
            registry=ModelRegistry(directory)
            row=registry.save('a'*32,{'revision':0,'name':'registered','provider':'openai','model':'gpt-4o-mini','uses':['decision']})
            row['versions']['1']['model_id']='b'*32
            version=row['versions']['1'];version['sha256']=digest({k:v for k,v in version.items() if k!='sha256'})
            write_json_atomic(registry.path('a'*32),row)
            with self.assertRaises(ModelConflict):
                registry.resolve({'model_id':'a'*32,'revision':1},'decision')


if __name__=='__main__':
    unittest.main()
