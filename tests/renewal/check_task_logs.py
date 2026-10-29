import datetime, unittest, importlib.util

class TaskLogTest(unittest.TestCase):
 def test_held_transcription_logs_are_scoped_and_do_not_invent_completion(self):
  self.assertIsNotNone(importlib.util.find_spec('video_service.postgres.task_logs'),'task-specific durable logs are missing')
  from video_service.postgres.task_logs import project_logs
  start=datetime.datetime(2026,10,29,13,27,1,tzinfo=datetime.timezone.utc)
  run={'id':'a'*32,'node_id':'transcribe','node_type':'transcribe','status':'running','started_at':start,'completed_at':None,'error_code':None,'request':{'password':'DO-NOT-ECHO'}}
  role={'phase':'held','held_reason':'model_reply_unknown','created_at':start,'received_at':None,'used_calls':1,'result_status':'held'}
  calls=[{'chunk_index':0,'status':'unknown','created_at':start,'error_code':'outcome_unknown','response':'DO-NOT-ECHO'}]
  value=project_logs(run,role,calls)
  self.assertEqual(value['state'],'held');self.assertEqual(value['received_responses'],0)
  self.assertTrue(any('구간 1' in row['message'] for row in value['entries']))
  self.assertTrue(any('응답' in row['message'] and '확인' in row['message'] for row in value['entries']))
  self.assertNotIn('DO-NOT-ECHO',str(value));self.assertFalse(any('완료'==row['message']for row in value['entries']))
  self.assertTrue(any(row['at'] is None for row in value['entries']))
 def test_no_logs_is_not_fake_processing_and_cpu_completion_uses_real_time(self):
  from video_service.postgres.task_logs import project_logs
  base={'id':'b'*32,'node_id':'encode','node_type':'encode','status':'waiting','started_at':None,'completed_at':None,'error_code':None}
  self.assertEqual(project_logs(base,None,[])['entries'],[])
  self.assertEqual(project_logs({**base,'status':'completed','started_at':'2026-10-29T13:00:00Z','completed_at':'2026-10-29T13:01:00Z'},None,[])['entries'][-1]['at'],'2026-10-29T13:01:00Z')
 def test_unknown_error_strings_are_not_exposed(self):
  from video_service.postgres.task_logs import project_logs
  run={'id':'c'*32,'node_id':'encode','node_type':'encode','status':'failed','started_at':None,'completed_at':None,'error_code':'Bearer DO-NOT-ECHO'}
  self.assertNotIn('DO-NOT-ECHO',str(project_logs(run,None,[])))

if __name__=='__main__':unittest.main()
