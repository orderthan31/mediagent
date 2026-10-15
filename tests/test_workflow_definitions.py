import importlib.util
import tempfile
import unittest
from pathlib import Path


def document():
    return {'catalog_version':1,'revision':0,'name':'편집 검증용', 'inputs':{'video':'video'},
            'nodes':[{'id':'n1','type':'analyze','position':{'x':340,'y':100},'options':{}}],
            'edges':[{'id':'e1','source':{'node':'$input','port':'video'},'target':{'node':'n1','port':'video'}}]}


class DefinitionTests(unittest.TestCase):
    def test_real_storage_roundtrip_revision_and_owner(self):
        self.assertIsNotNone(importlib.util.find_spec('video_service.workflow_definitions'), 'Server editor storage is not implemented')
        from video_service.workflow_definitions import DefinitionStore, DefinitionConflict
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=DefinitionStore(root,None);payload=document();identity='a'*32
            saved=store.save(identity,payload)
            self.assertEqual(saved['revision'],1)
            self.assertEqual(store.get(identity)['nodes'],payload['nodes'])
            self.assertEqual(store.get(identity)['edges'],payload['edges'])
            self.assertEqual(store.list()[0]['name'],payload['name'])
            with self.assertRaises(DefinitionConflict):store.save(identity,payload)
            with self.assertRaises(FileNotFoundError):DefinitionStore(root,'other-owner').get(identity)
            self.assertEqual(DefinitionStore(root,'other-owner').list(),[])
            payload.update(revision=1,name='이름 수정')
            payload['nodes'][0]['position']={'x':550,'y':220}
            store.save(identity,payload)
            self.assertEqual(store.get(identity)['nodes'][0]['position'],{'x':550,'y':220})
            self.assertEqual(store.get(identity)['revision'],2)

    def test_catalog_graph_checks_and_invalid_document_is_not_written(self):
        import copy
        import video_service.workflow_definitions as module
        self.assertTrue(hasattr(module,'validate_graph'), 'Server graph validation is not implemented')
        self.assertTrue(module.validate_graph(document())['valid'])
        from video_service.node_contracts import NODES
        for spec in NODES:
            graph=document();graph['inputs']=dict(spec['inputs']);graph['nodes'][0]['type']=spec['id']
            graph['edges']=[{'id':'e'+str(i),'source':{'node':'$input','port':p},'target':{'node':'n1','port':p}} for i,p in enumerate(spec['inputs'])]
            self.assertTrue(module.validate_graph(graph)['valid'],spec['id'])
        for kind in ('missing','type','dangling','cycle','options','duplicate','position'):
            graph=copy.deepcopy(document())
            if kind=='missing':graph['edges']=[]
            if kind=='type':graph['inputs']['video']='audio'
            if kind=='dangling':graph['edges'][0]['source']['node']='gone'
            if kind=='cycle':
                graph['nodes'][0]['type']='preprocess_audio'
                graph['edges'][0].update(source={'node':'n1','port':'audio'},target={'node':'n1','port':'audio'})
            if kind=='options':graph['nodes'][0]['options']={'unsupported':True}
            if kind=='duplicate':graph['edges'].append({**graph['edges'][0],'id':'e2'})
            if kind=='position':graph['nodes'][0]['position']['x']=float('nan')
            with self.subTest(kind=kind):
                result=module.validate_graph(graph)
                self.assertFalse(result['valid']);self.assertTrue(result['issues'])
                with tempfile.TemporaryDirectory() as directory:
                    store=module.DefinitionStore(Path(directory))
                    with self.assertRaises(ValueError):store.save('b'*32,graph)
                    self.assertEqual(store.list(),[])

    def test_real_api_endpoints_save_reload_conflict_and_body_limit(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import settings_routes
        with tempfile.TemporaryDirectory() as directory, patch.object(settings_routes,'settings',SimpleNamespace(storage_root=Path(directory))):
            app=FastAPI();app.state.auth=SimpleNamespace(store=None);app.state.cors_origins=['http://testserver'];app.include_router(settings_routes.router)
            with TestClient(app) as client:
                base='/api/settings/workflow-definitions';path=base+'/'+('c'*32);data=document()
                self.assertEqual(client.get(base).status_code,200)
                self.assertEqual(client.post(base+'/validate',json=data).json()['valid'],True)
                self.assertEqual(client.put(path,json=data).status_code,200)
                self.assertEqual(client.get(path).json()['revision'],1)
                self.assertEqual(client.get(base).json()['definitions'][0]['name'],data['name'])
                self.assertEqual(client.put(path,json=data).status_code,409)
                data['revision']=1;data['edges']=[]
                self.assertEqual(client.put(path,json=data).status_code,422)
                self.assertEqual(client.get(path).json()['revision'],1)
                self.assertEqual(client.get(base+'/'+('d'*32)).status_code,404)
                self.assertEqual(client.put(path,content='x'*131073,headers={'Content-Type':'application/json'}).status_code,413)
                self.assertEqual(client.put(path,json=document(),headers={'Origin':'https://evil.invalid'}).status_code,403)
