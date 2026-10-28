import pathlib,sys,unittest,tempfile,subprocess,shutil,hashlib,uuid,json,os
root=pathlib.Path(__file__).parents[2];sys.path.insert(0,str(root/'packages/shared'))
from video_service import cpu_agents
class CPUHub(unittest.TestCase):
 def test_real_analysis_returns_original_result_through_hub(self):
  with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])as text:
   base=pathlib.Path(text);inputs=base/'input';outputs=base/'output';(inputs/'blobs').mkdir(parents=True);outputs.mkdir();video=base/'source.mp4'
   subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=black:s=32x32:r=1:d=1','-c:v','libx264',str(video)],check=True)
   data=video.read_bytes();sha=hashlib.sha256(data).hexdigest();(inputs/'blobs'/sha).write_bytes(data)
   command={'protocol_version':1,'run_id':uuid.uuid4().hex,'attempt_id':uuid.uuid4().hex,'generation':1,'agent':{'id':'analyze','revision':'1'},'inputs':{'video':{'storage_key':'blobs/'+sha,'sha256':sha,'bytes':len(data),'type':'video'}},'options':{}}
   result=cpu_agents.run(command,inputs,outputs,agent='analyze');self.assertEqual(result['status'],'completed')
   marker=outputs/(command['run_id']+'-'+command['attempt_id'])/'tool-hub.json'
   self.assertFalse(marker.exists(),'plain CPU executor must not require the optional agent framework')
if __name__=='__main__':unittest.main()
