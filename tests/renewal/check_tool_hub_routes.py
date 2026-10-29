"""Pure endpoint projection test: no server, DB access, auth bypass or media call."""
import unittest
from fastapi import FastAPI
from app.tool_hub_routes import mount_tool_hub
class ToolRoutesTest(unittest.TestCase):
 def test_goal_agents_are_real_graph_registrations_not_model_tool_aliases(self):
  import importlib
  from app.tool_hub_routes import AGENTS
  from video_service.tool_hub import CALLER_TOOLS
  self.assertEqual(set(AGENTS),{'transcribe','translate'},'goal agent catalog is empty')
  for identity,entry in AGENTS.items():
   module,target=entry['entrypoint'].split(':');cls,method=target.split('.')
   implementation=getattr(importlib.import_module(module),cls)
   self.assertTrue(callable(getattr(implementation,method)))
   self.assertEqual(implementation.registration['id'],identity)
   self.assertEqual(set(CALLER_TOOLS['agent:'+identity]),set(entry['allowed_tools']))
   self.assertGreater(len(entry['allowed_tools']),1)
   self.assertFalse(entry['model_driven_selection'])
 def test_real_execution_projection_does_not_expose_requests_or_guess_expired_progress(self):
  import app.tool_hub_routes as routes
  self.assertTrue(hasattr(routes,'project_execution'),'agent page has no real task progress projection')
  base={'task_id':'a'*32,'job_id':'b'*32,'ticket_number':28,'phase':'accepted','node_status':'completed','completed_calls':2,'lease_valid':False,'cancel_requested':False,'held_reason':None,'created_at':None,'completed_at':None,'request':'SECRET','envelope':{'provider_key':'SECRET'}}
  completed=routes.project_execution(base)
  self.assertEqual(completed['status'],'completed')
  self.assertEqual(completed['completed_calls'],2)
  self.assertNotIn('SECRET',str(completed));self.assertNotIn('envelope',completed)
  unknown=routes.project_execution({**base,'phase':'sent','node_status':'running'})
  self.assertEqual(unknown['status'],'unknown')
  active=routes.project_execution({**base,'phase':'sent','node_status':'running','lease_valid':True})
  self.assertEqual(active['status'],'processing')
  self.assertEqual(routes.project_execution({**base,'cancel_requested':True,'node_status':'cancelled','phase':'cancelled'})['status'],'cancelled')
 def test_existing_executor_detail_uses_standard_definition_projection(self):
  app=FastAPI();mount_tool_hub(app,lambda:None,object())
  endpoint=next(r.endpoint for r in app.routes if getattr(r,'path','')=='/api/tool-hub/executors/{identity}')
  value=endpoint('transcribe',None)
  self.assertFalse(value['autonomous']);self.assertEqual(value['kind'],'task_agent');self.assertEqual(value['agent_id'],'transcribe');self.assertIn('speech.transcribe',[tool['id']for tool in value['tools']])
  self.assertEqual(value['tools'][0]['input_schema']['type'],'object')
if __name__=='__main__':unittest.main()
