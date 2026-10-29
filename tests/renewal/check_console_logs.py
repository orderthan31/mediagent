import unittest,importlib.util,tempfile,os,contextlib,io,sys
class ConsoleTest(unittest.TestCase):
 def test_real_stderr_is_redacted_preserved_and_task_bound(self):
  self.assertIsNotNone(importlib.util.find_spec('video_service.task_console'),'real task console capture is missing')
  from video_service.task_console import capture_console,read_console
  with tempfile.TemporaryDirectory()as root:
   native=io.StringIO()
   with contextlib.redirect_stderr(native):
    with capture_console('1'*32,root=root,secrets=('sensitive-provider-value',)):
     print('ValueError: HTTP 401 sensitive-provider-value Authorization: Bearer token-value',file=sys.stderr)
   data=read_console('1'*32,root=root)
   self.assertEqual(len(data['lines']),1)
   self.assertIn('HTTP 401',data['lines'][0]['text'])
   self.assertNotIn('sensitive-provider-value',str(data));self.assertNotIn('token-value',str(data))
   self.assertEqual(data['lines'][0]['stream'],'stderr')
   self.assertEqual(read_console('2'*32,root=root)['lines'],[])
   self.assertIn('HTTP 401',native.getvalue())

 def test_http_failure_keeps_safe_status_and_response(self):
  import httpx
  from video_service.model_endpoints import OpenAITextAdapter,EndpointFailure
  client=OpenAITextAdapter('https://api.example.com/v1',api_key='provider-secret-value',approved_origins={'https://api.example.com'},transport=httpx.MockTransport(lambda request:httpx.Response(401,json={'error':{'message':'invalid provider-secret-value'}})))
  try:
   with self.assertRaises(EndpointFailure)as caught:client._request('GET','/models')
   self.assertEqual(getattr(caught.exception,'http_status',None),401)
   self.assertIn('invalid',caught.exception.upstream_detail)
   self.assertNotIn('provider-secret-value',caught.exception.upstream_detail)
  finally:client.close()


 def test_cpu_child_stderr_is_forwarded_without_changing_stdout(self):
  from video_service.cpu_agents import process
  stream=io.StringIO()
  with contextlib.redirect_stderr(stream):
   out=process([sys.executable,'-c',"import sys;sys.stderr.write('native child diagnostic\\n');sys.stdout.write('wire-result')"])
  self.assertEqual(out,b'wire-result');self.assertIn('native child diagnostic',stream.getvalue())


 def test_bounded_child_retains_stderr(self):
  from pathlib import Path
  from video_service.cpu_agents import process_bounded
  with tempfile.TemporaryDirectory()as folder:
   target=Path(folder)/'output';stream=io.StringIO()
   script="import sys,pathlib;sys.stderr.write('bounded native diagnostic\\n');pathlib.Path(sys.argv[1]).write_bytes(b'x')"
   with contextlib.redirect_stderr(stream):process_bounded([sys.executable,'-c',script,str(target)],output=target,cwd=folder,timeout=3,max_bytes=10)
   self.assertIn('bounded native diagnostic',stream.getvalue());self.assertEqual(target.read_bytes(),b'x')


 def test_archive_outlives_worker_directory(self):
  import pathlib,shutil,json
  from video_service.agent_pool_host import PoolHost
  from video_service.task_console import capture_console,read_console
  with tempfile.TemporaryDirectory()as root:
   host=object.__new__(PoolHost);host.root=pathlib.Path(root)
   worker=host.root/'instance'/'console'
   with contextlib.redirect_stderr(io.StringIO()):
    with capture_console('3'*32,root=worker):print('original native exception',file=sys.stderr)
   host.archive_console({'id':'instance'})
   shutil.rmtree(host.root/'instance')
   self.assertIn('original native exception',read_console('3'*32,root=host.root/'console')['lines'][0]['text'])
   self.assertEqual(read_console('4'*32,root=host.root/'console')['lines'],[])

if __name__=='__main__':unittest.main()
