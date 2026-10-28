import pathlib,sys,unittest
root=pathlib.Path(__file__).parents[2];sys.path.insert(0,str(root/'packages/shared'))
class CatalogTest(unittest.TestCase):
 def test_standard_definition_projection_has_no_custom_invoke_api(self):
  from video_service import tool_hub
  self.assertFalse(hasattr(tool_hub,'ToolHub'))
  self.assertEqual([d['id']for d in tool_hub.allowed_definitions('model:translation')],['text.translate'])
  self.assertEqual(next(t for t in tool_hub.catalog()if t['executor']=='vocalization')['name'],'음성 구간 분석')
if __name__=='__main__':unittest.main()
