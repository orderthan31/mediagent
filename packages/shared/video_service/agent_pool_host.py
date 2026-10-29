"""Trusted template-bound ControlNet pool. Not imported by product API code."""
import copy,hashlib,json,time,uuid
from pathlib import Path
from .agent_pool import decide,transient_observation
from .control_runtime import PinnedEngine

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class PoolHost:
 def __init__(self,database,config):
  self.database=database;self.config=config;self.templates=config['templates']
  self.root=Path(config['status_root']);self.root.mkdir(parents=True,exist_ok=True)
  # Reuse the existing host-owned Unix engine transport; no socket is exposed to API.
  self.socket_path=config['docker_socket'];self.transport=PinnedEngine._request.__get__(self)
  import psycopg
  self.guard=psycopg.connect(database.dsn,autocommit=True,connect_timeout=5)
  if not self.guard.execute("SELECT pg_try_advisory_lock(hashtextextended(current_database()||':agent-pool-controlnet',0))").fetchone()[0]:raise ValueError('pool_controlnet_already_owned')
  for role,t in self.templates.items():
   for body in [t['create'],*t.get('extra_creates',[])]:
    if body['Image'][:7]!='sha256:'or body['HostConfig']['RestartPolicy']['Name']!='no':raise ValueError('fixed_local_image_and_no_restart_required')
   if t['policy']['max_instances']!=1+len(t.get('extra_creates',[])):raise ValueError('distinct_preapproved_slot_templates_required')
   if not t['policy']['idle_seconds']>0:raise ValueError('idle_policy_required')
 def event(self,db,item,event):
  db.execute('INSERT INTO agent_pool_events(instance_id,role,event)VALUES(%s,%s,%s)',(item['id'],item['role'],event))
 def request(self,method,path,body=None):
  return self.transport(method,path,body)
 def inspect(self,item):
  row=json.loads(self.request('GET','/v1.45/containers/'+(item['container_id']or self.name(item))+'/json'))
  expected=self.templates[item['role']]
  labels=row['Config'].get('Labels')or{}
  if row['Image']!=expected['create']['Image']or labels.get('mideagent.pool.instance')!=item['id']or labels.get('mideagent.pool.template')!=item['template_sha256']:raise ValueError('pool_instance_identity_changed')
  return row
 @staticmethod
 def name(item):return 'mideagent-pool-'+item['role']+'-'+str(item['slot'])+'-'+item['id'][:12]
 def payload(self,item):
  template=self.templates[item['role']]
  body=copy.deepcopy(template['create']if item['slot']==0 else template['extra_creates'][item['slot']-1])
  body['Labels']={**body.get('Labels',{}),'mideagent.pool.instance':item['id'],'mideagent.pool.template':item['template_sha256'],'mideagent.pool.role':item['role']}
  body['Env']=[x for x in body.get('Env',[])if not x.startswith(('MIDEAGENT_INSTANCE_ID=','MIDEAGENT_INSTANCE_STATUS_FILE='))]+['MIDEAGENT_INSTANCE_ID='+item['id'],'MIDEAGENT_INSTANCE_STATUS_FILE=/run/pool-status/status.json']
  (self.root/item['id']).mkdir(exist_ok=True)
  mount={'Type':'bind','Source':self.config['engine_status_root'].rstrip('/')+'/'+item['id'],'Target':'/run/pool-status','ReadOnly':False}
  body['HostConfig'].setdefault('Mounts',[]).append(mount)
  return body
 def archive_console(self,item):
  from .task_console import read_console
  folder=self.root/item['id']/'console';destination=self.root/'console'
  if not folder.exists():return
  destination.mkdir(exist_ok=True)
  for path in folder.glob('*.jsonl'):
   if path.is_symlink():continue
   try:records=read_console(path.stem,root=folder)
   except ValueError:continue
   if not records['lines']:continue
   raw=''.join(json.dumps({'task_id':path.stem,**line},ensure_ascii=False)+'\n'for line in records['lines'])
   temp=destination/(path.stem+'.tmp');temp.write_text(raw);temp.replace(destination/(path.stem+'.jsonl'))
 def observe(self,item):
  try:actual=self.inspect(item)
  except Exception:
   if item['container_id']:raise
   return None
  if not item['container_id']:
   with self.database.connection()as db:db.execute("UPDATE agent_pool_instances SET container_id=%s,phase='starting'WHERE id=%s AND container_id IS NULL",(actual['Id'],item['id']))
   item={**item,'container_id':actual['Id'],'phase':'starting'}
  self.archive_console(item)
  if not actual['State']['Running']:
   if item['phase']=='stopping':
    report=json.loads((self.root/item['id']/'status.json').read_text())
    if actual['State']['ExitCode']!=0 or report['phase']!='stopped'or report['unsettled']:raise ValueError('pool_exit_not_settled')
    self.request('DELETE','/v1.45/containers/'+item['container_id']+'?force=false&v=false')
    with self.database.connection()as db:
     db.execute("UPDATE agent_pool_instances SET phase='removed',observed_at=now()WHERE id=%s",(item['id'],));self.event(db,item,'removed')
   elif item['phase']=='starting'and not item.get('start_issued_at'):
    with self.database.connection()as db:db.execute('UPDATE agent_pool_instances SET start_issued_at=now()WHERE id=%s AND start_issued_at IS NULL',(item['id'],));self.event(db,item,'start_issued')
    self.request('POST','/v1.45/containers/'+item['container_id']+'/start')
   return actual
  if item['phase']in {'draining','stopping'}or item['phase']=='held'and item.get('stop_issued_at'):return actual
  reportPath=self.root/item['id']/'status.json'
  if not reportPath.exists():return actual
  report=json.loads(reportPath.read_text())
  if report['instance_id']!=item['id']or time.time()-report['observed_at']>5:return actual
  from datetime import datetime
  started=datetime.fromisoformat(actual['State']['StartedAt'].replace('Z','+00:00')).timestamp()
  if report['started_at']<started-1:return actual
  if report['phase']not in {'ready','busy'}:return actual
  with self.database.connection()as db:
   if item.get('error_code'):self.event(db,item,'observation_restored')
   db.execute("UPDATE agent_pool_instances SET phase=%s,boot_id=%s,observed_at=now(),ready_at=%s,last_completed_at=%s,unsettled=%s,error_code=NULL WHERE id=%s AND phase IN('starting','ready','busy','held')AND stop_issued_at IS NULL",(report['phase'],report['boot_id'],report['ready_at'],report['last_completed_at'],report['unsettled'],item['id']))
  return actual
 def tick(self):
  with self.database.connection()as db:instances=db.execute("SELECT * FROM agent_pool_instances WHERE phase<>'removed'ORDER BY created_at").fetchall()
  for item in instances:
   try:self.observe(item)
   except Exception as error:
    if transient_observation(error):continue
    with self.database.connection()as db:db.execute("UPDATE agent_pool_instances SET phase='held',error_code=%s WHERE id=%s",('pool_observation_'+type(error).__name__,item['id']))
  with self.database.connection()as db:
   instances=db.execute("SELECT * FROM agent_pool_instances WHERE phase<>'removed'ORDER BY created_at").fetchall()
   policies={p['role']:p for p in db.execute('SELECT * FROM agent_pool_roles WHERE enabled').fetchall()}
   capacity={p['role']:p for p in db.execute('SELECT * FROM agent_pool_capacity').fetchall()}
  used=sum(policies[i['role']]['memory_bytes']for i in instances if i['role']in policies)
  free=max(0,self.config['memory_budget_bytes']-used)
  for role,policy in policies.items():
   if role not in self.templates:continue
   if policy['template_sha256']!=digest(self.templates[role]):raise ValueError('pool_template_policy_changed')
   own=[i for i in instances if i['role']==role];d=capacity.get(role,{'queued':0,'inflight':0})
   plan=decide(policy,own,queued=d['queued'],inflight=d['inflight'],now=time.time(),available_memory=free)
   for _ in range(plan['start']):
    slots={i['slot']for i in own};slot=next((n for n in range(policy['max_instances'])if n not in slots),None)
    if slot is None:break
    item={'id':uuid.uuid4().hex,'role':role,'slot':slot,'phase':'creating','container_id':None,'template_sha256':policy['template_sha256']}
    with self.database.connection()as db:
     db.execute("INSERT INTO agent_pool_instances(id,role,slot,template_sha256,phase)VALUES(%s,%s,%s,%s,'creating')",(item['id'],role,slot,item['template_sha256']));self.event(db,item,'create_issued')
    try:
     created=json.loads(self.request('POST','/v1.45/containers/create?name='+self.name(item),self.payload(item)))
     with self.database.connection()as db:db.execute("UPDATE agent_pool_instances SET container_id=%s,phase='starting'WHERE id=%s",(created['Id'],item['id']))
    except Exception:pass # same durable identity is inspected next tick; never mint another slot
    free-=policy['memory_bytes'];own.append(item)
   for identity in plan['drain']:
    item=next(i for i in own if i['id']==identity)
    if item['unsettled']or not item['observed_at']or time.time()-item['observed_at'].timestamp()>5:continue
    with self.database.connection()as db:
     # Serialize with application capacity reservation so no new task slips in.
     db.execute("SELECT pg_advisory_xact_lock(hashtextextended('agent-pool-capacity:'||%s,0))",(role,))
     demand=db.execute('SELECT * FROM agent_pool_capacity WHERE role=%s',(role,)).fetchone()
     if demand and(demand['queued']or demand['inflight']):continue
     changed=db.execute("UPDATE agent_pool_instances SET phase='stopping',stop_issued_at=now()WHERE id=%s AND phase='ready'AND unsettled=0 RETURNING id",(identity,)).fetchone()
     if not changed:continue
     self.event(db,item,'stop_issued')
    try:self.request('POST','/v1.45/containers/'+item['container_id']+'/kill?signal=SIGTERM')
    except Exception:pass # never resend an uncertain signal or force-kill work
 def close(self):self.guard.close()
