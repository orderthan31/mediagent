"""Pure endpoint projection test: no server, DB access, auth bypass or media call."""
import unittest
from fastapi import FastAPI
from app.tool_hub_routes import mount_tool_hub
class ToolRoutesTest(unittest.TestCase):
 def test_existing_executor_detail_uses_standard_definition_projection(self):
  app=FastAPI();mount_tool_hub(app,lambda:None,object())
  endpoint=next(r.endpoint for r in app.routes if getattr(r,'path','')=='/api/tool-hub/executors/{identity}')
  value=endpoint('transcribe',None)
  self.assertFalse(value['autonomous']);self.assertEqual(value['tools'][0]['id'],'speech.transcribe')
  self.assertEqual(value['tools'][0]['input_schema']['type'],'object')
if __name__=='__main__':unittest.main()
