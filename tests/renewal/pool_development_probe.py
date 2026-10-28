import sys,json,uuid
from pathlib import Path
from app.server import load_bootstrap
from app.operator import runtime_components
from video_service.postgres import Database
from video_service.postgres.execution import Execution
import video_service.postgres
video_service.postgres.__path__.insert(0,'/tmp/agent-pool-source/postgres')
from video_service.postgres.agent_pool import AgentPool
from video_service.model_role_coordinator import ModelRoleCoordinator
config,dsn=load_bootstrap(sys.argv[1]);db=Database(dsn)
store,credentials,factory=runtime_components(db,config,enable_broker=True,enable_registered=True,enable_nonpaid=True)
runtime=Execution(db,store,translation_runtime=factory.translation_runtime,transcription_runtime=factory.transcription_runtime,vocalization_runtime=factory.vocalization_runtime,engine_runtime_enabled=True)
owner=sys.argv[2]
job=runtime.create(owner,'65198a605afc4b8c9e7a47bebb2b831b','9bbe37e7127d4e7aa4624246bc45fe74',2,request_id='pool-lifecycle-normal-probe-1',options={'source_language':'en','target_language':'ko'})
job=ModelRoleCoordinator(runtime,factory).auto_enroll_new_job(owner,job['id'],'pool-probe-roles-1')
if job['status']=='draft':
 plan=runtime.plan(owner,job['id']);assert plan['ready']
 consent=runtime.confirm(owner,job['id'],plan['token'],'pool-probe-confirm-1')
 runtime.admit(owner,job['id'],consent['id'],'pool-probe-admit-1')
AgentPool(runtime).enroll(owner,job['id'])
with db.connection()as c:
 raw=runtime._job(c,owner,job['id'],lock=True)
 node=next(n for n in raw['snapshot']['definition']['nodes']if n['type']=='analyze')
 ready=AgentPool.ready_in(c,raw,node)
 count=c.execute('SELECT count(*)n FROM node_runs WHERE job_id=%s',(job['id'],)).fetchone()['n']
 assert not ready,'missing cold-start gate: worker not booted but role was admitted'
 assert count==0
print(json.dumps({'job_id':job['id'],'ticket_number':job['ticket_number'],'ready':ready,'node_runs':count,'actual_existing_dev_runtime':True}))
