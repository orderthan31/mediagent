import importlib.util, pathlib, unittest
p=pathlib.Path(__file__).parents[2]/'packages/shared/video_service/agent_pool.py'
class PoolLifecycle(unittest.TestCase):
 def test_demand_creates_only_missing_capacity_and_reuses_booting_instance(self):
  self.assertTrue(p.exists(),'on-demand pool implementation missing')
  s=importlib.util.spec_from_file_location('agent_pool',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  policy={'max_instances':2,'memory_bytes':512,'idle_seconds':30}
  self.assertEqual(m.decide(policy,[],queued=1,inflight=0,now=100,available_memory=512),{'start':1,'drain':[]})
  boot=[{'id':'first','phase':'starting','last_completed_at':None}]
  self.assertEqual(m.decide(policy,boot,queued=1,inflight=0,now=101,available_memory=512),{'start':0,'drain':[]})
 def test_idle_reclaims_only_after_delivery_and_actual_completion_keepalive(self):
  s=importlib.util.spec_from_file_location('agent_pool',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  policy={'max_instances':2,'memory_bytes':512,'idle_seconds':30}
  idle=[{'id':'first','phase':'ready','last_completed_at':50,'ready_at':10,'heartbeat_at':100}]
  self.assertEqual(m.decide(policy,idle,queued=0,inflight=0,now=100,available_memory=0)['drain'],['first'])
  self.assertEqual(m.decide(policy,idle,queued=0,inflight=1,now=100,available_memory=0)['drain'],[])
  self.assertEqual(m.decide(policy,idle,queued=1,inflight=0,now=100,available_memory=0)['drain'],[])
 def test_worker_readiness_and_completed_time_do_not_follow_heartbeats(self):
  import sys,tempfile,os,json
  sys.path.insert(0,str(p.parent.parent))
  from video_service.worker_lifecycle import WorkerPulse
  with tempfile.TemporaryDirectory()as root:
   target=pathlib.Path(root)/'status.json';old=dict(os.environ)
   try:
    os.environ['MIDEAGENT_INSTANCE_STATUS_FILE']=str(target);os.environ['MIDEAGENT_INSTANCE_ID']='role-instance'
    pulse=WorkerPulse();self.assertEqual(json.loads(target.read_text())['phase'],'starting')
    pulse.emit('ready');pulse.emit('busy');pulse.emit('ready',completed=True)
    completed=json.loads(target.read_text())['last_completed_at'];pulse.tick(force=True)
    self.assertEqual(json.loads(target.read_text())['last_completed_at'],completed)
    pulse.emit('stopped');self.assertEqual(json.loads(target.read_text())['phase'],'stopped')
   finally:os.environ.clear();os.environ.update(old)
if __name__=='__main__':unittest.main()
