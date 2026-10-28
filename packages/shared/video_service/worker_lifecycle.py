"""Local execution-host observation, written only by the pinned worker process."""
import json,os,time,uuid
from pathlib import Path

class WorkerPulse:
 def __init__(self):
  text=os.environ.get('MIDEAGENT_INSTANCE_STATUS_FILE');self.path=Path(text)if text else None
  self.instance=os.environ.get('MIDEAGENT_INSTANCE_ID');self.boot=uuid.uuid4().hex
  self.phase='starting';self.started=time.time();self.ready_at=None;self.completed=None;self.unsettled=0;self.last_write=0
  self.emit('starting')
 def emit(self,phase,*,completed=False,unsettled=0):
  self.phase=phase;self.unsettled=unsettled
  if phase=='ready'and self.ready_at is None:self.ready_at=time.time()
  if completed:self.completed=time.time()
  self.tick(force=True)
 def tick(self,*,force=False):
  if self.path is None:return
  now=time.time()
  if not force and now-self.last_write<1:return
  self.path.parent.mkdir(parents=True,exist_ok=True)
  value={'instance_id':self.instance,'boot_id':self.boot,'phase':self.phase,'started_at':self.started,'ready_at':self.ready_at,'last_completed_at':self.completed,'unsettled':self.unsettled,'observed_at':now}
  tmp=self.path.with_name(self.path.name+'.'+str(os.getpid())+'.tmp');tmp.write_text(json.dumps(value));os.replace(tmp,self.path);self.last_write=now
