import pathlib,unittest,json,hashlib,tempfile,subprocess,uuid
class StandardToolsTest(unittest.TestCase):
 def test_registered_executor_is_a_standard_typed_tool(self):
  import video_service
  self.assertTrue((pathlib.Path(video_service.__path__[0])/'standard_tools.py').exists(),'standard bound Tool adapter missing')
  from langchain_core.tools import StructuredTool
  from pydantic import ValidationError
  from video_service.standard_tools import standard_tools
  entered=[]
  def registered(source):entered.append(source);return {'status':'completed','outputs':{}}
  tools=standard_tools('model:transcription',{'speech.transcribe':registered})
  self.assertEqual(len(tools),1);tool=tools[0];self.assertIsInstance(tool,StructuredTool)
  reference={'storage_key':'blobs/'+'a'*64,'sha256':'a'*64,'bytes':10,'type':'audio'}
  self.assertEqual(tool.invoke({'source':reference})['status'],'completed');self.assertEqual(entered,[reference])
  with self.assertRaises(ValidationError):tool.invoke({'source':{**reference,'bytes':'not-a-size'}})
  self.assertEqual(len(entered),1)
 def test_real_langgraph_call_node_uses_standard_tool_inside_existing_fences(self):
  from mideagent_models.transcription import TranscriptionAgent
  with tempfile.TemporaryDirectory()as text:
   root=pathlib.Path(text);audio=root/'chunk.wav';audio.write_bytes(b'actual-controlled-unit-audio');data=audio.read_bytes();sha=hashlib.sha256(data).hexdigest()
   calls=[]
   def existing(model,raw,language):calls.append((raw,language));return []
   agent=TranscriptionAgent(root/'state',existing)
   task={'task_id':uuid.uuid4().hex,'model':{},'audio':{'sha256':sha,'bytes':len(data)},'source_language':'en','max_calls':1}
   agent.state.ensure(task['task_id'],'a'*64,task)
   result=agent._invoke({'task':task,'chunks':[{'index':0,'path':str(audio),'sha256':sha}],'index':0})
   self.assertEqual(result['status'],'received');self.assertEqual(calls,[(data,'en')])
   with agent.state.connect()as db:
    table=db.execute("SELECT name FROM sqlite_master WHERE name='standard_tool_calls'").fetchone()
    self.assertIsNotNone(table,'LangGraph call bypassed standard registered Tool')
    record=db.execute('SELECT tool_name FROM standard_tool_calls WHERE task=?',(task['task_id'],)).fetchone()
    self.assertEqual(record['tool_name'],'speech_transcribe')
   again=agent._invoke({'task':task,'chunks':[{'index':0,'path':str(audio),'sha256':sha}],'index':0});self.assertEqual(len(calls),1)
 def test_catalog_schema_is_the_actual_standard_tool_schema(self):
  from video_service.standard_tools import standard_tools
  from video_service.tool_hub import catalog
  def registered(source):return source
  tool=standard_tools('model:translation',{'text.translate':registered})[0]
  item=next(i for i in catalog()if i['id']=='text.translate')
  self.assertEqual(item['input_schema'],tool.get_input_schema().model_json_schema())
  with self.assertRaises(PermissionError):standard_tools('model:translation',{'speech.transcribe':registered})
 def test_existing_cpu_processor_can_be_bound_without_changing_cpu_code(self):
  from video_service.standard_tools import standard_tools
  from video_service.cpu_agents import run
  with tempfile.TemporaryDirectory()as text:
   root=pathlib.Path(text);inputs=root/'input';outputs=root/'output';(inputs/'blobs').mkdir(parents=True);outputs.mkdir();video=root/'source.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=32x32:r=1:d=1','-c:v','libx264',str(video)],check=True)
   raw=video.read_bytes();sha=hashlib.sha256(raw).hexdigest();(inputs/'blobs'/sha).write_bytes(raw);ref={'storage_key':'blobs/'+sha,'sha256':sha,'bytes':len(raw),'type':'video'}
   def registered(video):
    command={'protocol_version':1,'run_id':uuid.uuid4().hex,'attempt_id':uuid.uuid4().hex,'generation':1,'agent':{'id':'analyze','revision':'1'},'inputs':{'video':video},'options':{}}
    return run(command,inputs,outputs,agent='analyze')
   tool=standard_tools('cpu:analyze',{'media.analyze':registered})[0]
   result=tool.invoke({'video':ref});self.assertEqual(result['status'],'completed');self.assertTrue(result['outputs']['metadata']['sha256'])
 def test_translation_node_calls_standard_tool_and_preserves_existing_result(self):
  from mideagent_models.translation import TranslationAgent
  with tempfile.TemporaryDirectory()as text:
   calls=[]
   def registered(task,batch,candidate):calls.append(candidate);return {'status':'received','reply':'[]'}
   agent=TranslationAgent(pathlib.Path(text)/'state',registered)
   task={'task_id':uuid.uuid4().hex,'max_calls':1,'transcript':{'sha256':'b'*64,'bytes':2}}
   agent.state.ensure(task['task_id'],'c'*64,task)
   result=agent._invoke({'task':task,'batches':[object()],'batch':0,'candidate':0,'call_index':0})
   self.assertEqual(result['status'],'received');self.assertEqual(calls,[0])
   with agent.state.connect()as db:self.assertEqual(db.execute('SELECT tool_name FROM standard_tool_calls').fetchone()['tool_name'],'text_translate')
if __name__=='__main__':unittest.main()
