"""Application-side capacity demand. This module has no Docker/runtime authority."""
from psycopg.types.json import Jsonb

MODEL_ROLES={'transcribe':'transcription','translate':'translation','vocalize':'vocalization'}

def role_for(node):
 if node['type']in MODEL_ROLES:
  return MODEL_ROLES[node['type']]if node.get('model_ref')else None
 return node['type']if node['type']in {'analyze','extract_audio','preprocess_audio','generate_subtitle','encode','validate_video'}else None

class AgentPool:
 def __init__(self,runtime):self.runtime=runtime;self.database=runtime.database
 @staticmethod
 def enabled_in(db):
  return db.execute("SELECT to_regclass('agent_pool_roles') AS value").fetchone()['value']is not None
 @staticmethod
 def enrolled_in(db,job):
  if not AgentPool.enabled_in(db):return False
  return bool(db.execute('SELECT 1 FROM agent_pool_jobs WHERE owner_id=%s AND job_id=%s AND generation=%s AND claim_id=%s',(job['owner_id'],job['id'],job['generation'],job['active_claim_id'])).fetchone())
 def enroll(self,owner,identity):
  with self.database.connection()as db:
   job=self.runtime._job(db,owner,identity,lock=True)
   if not self.enabled_in(db):return
   if job['cancel_requested']or job['status']not in {'waiting','running'}or not job['active_claim_id']:return
   if db.execute('SELECT 1 FROM node_runs WHERE owner_id=%s AND job_id=%s LIMIT 1',(owner,identity)).fetchone():return
   db.execute('INSERT INTO agent_pool_jobs(owner_id,job_id,generation,claim_id)VALUES(%s,%s,%s,%s)ON CONFLICT DO NOTHING',(owner,identity,job['generation'],job['active_claim_id']))
 @staticmethod
 def ready_in(db,job,node):
  if not AgentPool.enrolled_in(db,job):return True
  role=role_for(node)
  if role is None:return True
  policy=db.execute('SELECT 1 FROM agent_pool_roles WHERE role=%s AND enabled',(role,)).fetchone()
  if not policy:return True
  db.execute('INSERT INTO agent_pool_demands(owner_id,job_id,generation,node_id,role)VALUES(%s,%s,%s,%s,%s)ON CONFLICT DO NOTHING',(job['owner_id'],job['id'],job['generation'],node['id'],role))
  if not db.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('agent-pool-capacity:'||%s,0)) locked",(role,)).fetchone()['locked']:return False
  live=db.execute("SELECT count(*) n,count(*)FILTER(WHERE phase='ready') ready FROM agent_pool_instances WHERE role=%s AND phase IN('ready','busy')AND observed_at>now()-interval '5 seconds'",(role,)).fetchone()
  inflight=db.execute('SELECT inflight FROM agent_pool_capacity WHERE role=%s',(role,)).fetchone()
  return live['ready']>0 and live['n']>(inflight['inflight']if inflight else 0)
 @staticmethod
 def assigned_in(db,job,node,run):
  if not AgentPool.enabled_in(db):return
  db.execute('UPDATE agent_pool_demands SET node_run_id=%s WHERE owner_id=%s AND job_id=%s AND generation=%s AND node_id=%s AND node_run_id IS NULL',(run['id'],job['owner_id'],job['id'],job['generation'],node['id']))
 def blocked(self,owner,identity):
  with self.database.connection()as db:
   if not self.enabled_in(db):return False
   job=self.runtime._job(db,owner,identity)
   if not self.enrolled_in(db,job):return False
   pending=db.execute('SELECT DISTINCT role FROM agent_pool_demands WHERE owner_id=%s AND job_id=%s AND generation=%s AND node_run_id IS NULL',(owner,identity,job['generation'])).fetchall()
   if not pending:return False
   for row in pending:
    role=row['role'];live=db.execute("SELECT count(*) n,count(*)FILTER(WHERE phase='ready') ready FROM agent_pool_instances WHERE role=%s AND phase IN('ready','busy')AND observed_at>now()-interval '5 seconds'",(role,)).fetchone();work=db.execute('SELECT inflight FROM agent_pool_capacity WHERE role=%s',(role,)).fetchone()
    if live['ready']and live['n']>(work['inflight']if work else 0):return False
   return True
 @staticmethod
 def preparing_in(db,job):
  if not AgentPool.enrolled_in(db,job):return False
  return bool(db.execute("SELECT 1 FROM agent_pool_demands WHERE owner_id=%s AND job_id=%s AND generation=%s AND node_run_id IS NULL LIMIT 1",(job['owner_id'],job['id'],job['generation'])).fetchone())
 def tick(self,controller):
  with self.database.connection()as db:
   if not self.enabled_in(db):return
   rows=db.execute("SELECT p.owner_id,p.job_id FROM agent_pool_jobs p JOIN jobs j ON j.owner_id=p.owner_id AND j.id=p.job_id AND j.generation=p.generation AND j.active_claim_id=p.claim_id WHERE j.status IN('waiting','running')AND NOT j.cancel_requested AND(EXISTS(SELECT 1 FROM agent_pool_demands d WHERE d.owner_id=p.owner_id AND d.job_id=p.job_id AND d.generation=p.generation AND d.node_run_id IS NULL)OR NOT EXISTS(SELECT 1 FROM node_runs r WHERE r.owner_id=p.owner_id AND r.job_id=p.job_id AND r.status IN('waiting','running')))ORDER BY p.created_at LIMIT 64").fetchall()
  for row in rows:controller.dispatch(row['owner_id'],row['job_id'])
