"""Workflow-selected product entry; executor kind is server-derived."""
import importlib.util
import unittest
from copy import deepcopy
from test_workflow_decision import decision_graph


class WorkflowEntryTests(unittest.TestCase):
    def test_saved_graph_selects_server_contract_without_user_engine_choice(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.workflow_entry'), 'Workflow-centered entry inspection missing')
        from video_service.workflow_entry import inspect_workflow
        graph=decision_graph()
        result=inspect_workflow(graph)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['contract'],'decision')
        self.assertEqual(result['definition_id'],graph['id'])
        self.assertEqual(result['definition_revision'],1)
        from video_service.decision_conditions import OPTIONS
        self.assertEqual(result['summary'][0]['options'],{'data_type':'video',**{key:values[0] for key,values in OPTIONS.items()}})
        self.assertFalse(result['runtime_connected'])
        self.assertIn('실행',result['notice'])
        invalid=deepcopy(graph)
        invalid['edges'][0]['target']['port']='missing'
        rejected=inspect_workflow(invalid)
        self.assertFalse(rejected['supported'])
        self.assertTrue(rejected['reasons'])
        self.assertIsNone(rejected['contract'])

    def test_entry_api_reads_saved_workflow_with_owner_revision_and_no_ticket_creation(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from video_service.workflow_definitions import DefinitionStore
        from app.api import settings_routes
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);graph=decision_graph();graph.pop('id');graph['revision']=0
            DefinitionStore(root).save('a'*32,graph)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root)),TestClient(app) as client:
                payload={'definition_id':'a'*32,'definition_revision':1}
                response=client.post('/api/settings/work-entry/inspect',json=payload)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['contract'],'decision')
                self.assertFalse(response.json()['runtime_connected'])
                self.assertEqual(client.post('/api/settings/work-entry/inspect',json={**payload,'definition_revision':2}).status_code,409)
                self.assertEqual(client.post('/api/settings/work-entry/inspect',json={**payload,'contract':'sequential'}).status_code,422)
                self.assertFalse(any(root.glob('.workflow-*-tickets/*/*/ticket.json')))
                self.assertEqual(DefinitionStore(root).get('a'*32)['revision'],1)

    def test_model_and_definition_inspection_io_is_off_the_api_event_loop(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from video_service.workflow_definitions import DefinitionStore
        from app.api import settings_routes
        from pathlib import Path
        import tempfile,threading
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);graph=decision_graph();graph.pop('id');graph['revision']=0
            DefinitionStore(root).save('a'*32,graph)
            original=DefinitionStore.get;reads=[]
            def traced_get(store,identity):
                reads.append(threading.get_ident());return original(store,identity)
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            async def loop_probe():
                return {'thread':threading.get_ident()}
            app.add_api_route('/loop-probe',loop_probe)
            with patch.object(settings_routes,'settings',SimpleNamespace(storage_root=root)),patch.object(DefinitionStore,'get',traced_get),TestClient(app) as client:
                loop=client.get('/loop-probe').json()['thread']
                response=client.post('/api/settings/work-entry/inspect',json={'definition_id':'a'*32,'definition_revision':1})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(reads)
                self.assertNotIn(loop,reads)


if __name__=='__main__':
    unittest.main()
