"""Isolated UI API fixture. Real Docker faults + PG + normal auth, no MQ/tickets.

Direct-PG reporting fixture, no RabbitMQ or product ticket processing claim.
All resources/credentials are newly generated and private to this run.
"""
import json,os,secrets,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from uuid import uuid4
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from app.renewal import create_app
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_recovery import ControlRecovery

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config=json.loads(Path(sys.argv[1]).read_text());assert config['scope']=='isolated-start-partial'
root=Path(config['private_root']);root.mkdir(exist_ok=True);source=Path(config['source'])
owner=Database(config['dsn']);assert urlsplit(config['dsn']).hostname=='127.0.0.1' and urlsplit(config['dsn']).path.startswith('/control_review_');owner.migrate()
roles={name:{'name':'review_'+name+'_'+uuid4().hex[:8],'password':secrets.token_urlsafe(32)} for name in ('api','host','report')}
def dsn(role,hostname=None,port=None):
    parts=urlsplit(config['dsn']);value=roles[role]
    return urlunsplit((parts.scheme,f"{value['name']}:{value['password']}@{hostname or parts.hostname}:{port or parts.port}",parts.path,'',''))
with owner.connection() as db:
    for role in roles.values():
        db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role['name']),sql.Literal(role['password'])))
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role['name'])))
    api=sql.Identifier(roles['api']['name']);host=sql.Identifier(roles['host']['name']);report=sql.Identifier(roles['report']['name'])
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(api))
    db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(api))
    control_tables='remote_control_groups,remote_control_requests,remote_control_actions,remote_control_batches,remote_control_reports,remote_control_ack_evidence,remote_control_review_heads,remote_control_review_plans,remote_control_review_decisions,remote_control_review_results,worker_observations,worker_observation_events,telemetry_observer'
    db.execute(sql.SQL('REVOKE ALL ON '+control_tables+' FROM {}').format(api))
    db.execute(sql.SQL('GRANT SELECT ON '+control_tables+' TO {}').format(api))
    db.execute(sql.SQL('GRANT UPDATE(revision,enabled,replicas,pending_request) ON remote_control_groups TO {}').format(api))
    db.execute(sql.SQL('GRANT INSERT ON remote_control_requests,remote_control_review_heads,remote_control_review_plans,remote_control_review_decisions TO {}').format(api))
    db.execute(sql.SQL('GRANT UPDATE(revision,pending_decision,last_decision) ON remote_control_review_heads TO {}').format(api))
    db.execute(sql.SQL('GRANT SELECT,INSERT ON remote_control_groups,remote_control_review_heads,remote_control_review_results,remote_control_ack_evidence,remote_control_actions,remote_control_batches TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(observed,observed_at,observation_revision,observation_sha256,pending_request,quarantined,revision) ON remote_control_groups TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(phase,error_code,updated_at) ON remote_control_requests TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(phase,issue_count,issued_at,updated_at) ON remote_control_actions TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(receipt_sha256,facts,valid,error_code,verified_at) ON remote_control_ack_evidence TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(pending_decision) ON remote_control_review_heads TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT ON remote_control_requests,remote_control_review_plans,remote_control_review_decisions,worker_observations,telemetry_observer TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT(id,active,role) ON accounts TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON worker_observations,worker_observation_events,telemetry_observer TO {}').format(report))
    db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(report))
api_db=Database(dsn('api'));store=RemoteControl(api_db);recovery=ControlRecovery(store)
from video_service.content_store import ContentStore
content_root=root/'content';content_root.mkdir()
app=create_app(api_db,allowed_origins=(config['origin'],'http://testserver'),secure_cookies=False,content_store=ContentStore(content_root),remote_control=store,control_recovery=recovery)
client=TestClient(app);password=secrets.token_urlsafe(32)
assert client.post('/api/auth/bootstrap',json={'username':'native-review-admin','password':password}).status_code==201
login=client.post('/api/auth/login',json={'username':'native-review-admin','password':password});assert login.status_code==200
headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']}
context=config['docker_context'];image=config['image_id'];created=[];results=[]
worker_source=source/'tests/renewal/control_start_partial_worker.py'
def docker(*args):
    p=subprocess.run(['docker','--context',context,*args],capture_output=True,text=True,timeout=40)
    assert p.returncode==0,'fixture_docker_command_failed';return p.stdout.strip()
def physical(cid):return json.loads(docker('inspect',cid))[0]['State']
def step(path,expected=0):
    p=subprocess.run([sys.executable,str(source/'tests/renewal/control_start_partial_host.py'),str(path)],capture_output=True,text=True,timeout=40)
    if p.returncode not in (0,23):
        (root/'host-failure.log').write_text(p.stdout+p.stderr)
        raise AssertionError('native_host_unexpected_exit_'+str(p.returncode))
    return p.returncode


import threading,uvicorn
from starlette.staticfiles import StaticFiles
from video_service.postgres.worker_telemetry import WorkerTelemetry
with owner.connection() as d:
    d.execute("CREATE TABLE start_partial_jobs(id text PRIMARY KEY,number bigint GENERATED ALWAYS AS IDENTITY UNIQUE,target_worker_id text NOT NULL,attempt_id text NOT NULL,state text NOT NULL DEFAULT 'queued',worker_id text,worker_boot text,duration_seconds integer NOT NULL CHECK(duration_seconds BETWEEN 1 AND 30),started_at timestamptz,completed_at timestamptz,claim_count integer NOT NULL DEFAULT 0,artifact bytea,sha256 text)")
    d.execute(sql.SQL('GRANT SELECT,UPDATE ON start_partial_jobs TO {}').format(sql.Identifier(roles['report']['name'])))
cases={};configs={};hidden={};faults=[];pause=False;job_ids={};sink=WorkerTelemetry(owner)
def beat():sink.beat()
def one(group):
    beat();code=step(Path(configs[group]['path']))
    if code==23:
        faults.append({'group':group,'at':time.time(),'exit':code})
        configs[group]['value']['fault_action']=None;Path(configs[group]['path']).write_text(json.dumps(configs[group]['value']))
    return code
for group,count,prep in [('analyze',1,False),('extract_audio',1,False),('encode',2,True)]:
    case=root/group;case.mkdir();key=case/'signing.key';key.write_bytes(secrets.token_bytes(32));targets=[]
    for i in range(count):
        wid=uuid4().hex;labels=[('com.docker.compose.project','isolated-start-partial'),('com.docker.compose.service',group),('mideagent.worker_id',wid),('mideagent.scope','isolated-start-partial')]
        envfile=case/(str(i)+'.env');envfile.write_text('\n'.join(['MIDEAGENT_CONTROL_DISPOSABLE=1','REVIEW_WORKER_ID='+wid,'REVIEW_ROLE='+group,'REVIEW_REPORT_DSN='+dsn('report','review-pg',5432)]).replace('\\n','\n'))
        args=['create','--name','start-partial-worker-'+uuid4().hex[:8],'--network',config['network'],'--restart','no','--read-only','--tmpfs','/tmp:rw,nosuid,size=64m','--env-file',str(envfile),'--mount','type=bind,source='+str(worker_source)+',target=/fixture/worker.py,readonly','--entrypoint','python']
        for k,v in labels:args+=['--label',k+'='+v]
        cid=docker(*args,image,'/fixture/worker.py');created.append(cid)
        if prep:docker('start',cid)
        targets.append({'worker_id':wid,'target_id':cid,'image_id':image,'labels':labels})
    value={'scope':config['scope'],'group':group,'targets':targets,'dsn':dsn('host'),'docker_context':context,'fault_action':'stop' if prep else 'start','receipts':str(case/'receipts'),'key_file':str(key),'call_log':str(case/'native-calls.jsonl')}
    path=case/'host.json';path.write_text(json.dumps(value));configs[group]={'path':str(path),'value':value};cases[group]={'workers':targets}
    for _ in range(40):
        one(group);v=store.get(group)
        if (prep and v['state']=='ready') or (not prep and v['observed_replicas']==0):break
        time.sleep(.2)
    if prep:
        assert v['state']=='ready'
        assert client.put('/api/admin/agents/'+group+'/configuration',json={'revision':0,'enabled':True,'replicas':2,'request_id':uuid4().hex},headers=headers).status_code==200
        one(group);assert store.get(group)['control']['phase'] is None
artifacts=Path(config['artifacts']);artifacts.mkdir(exist_ok=True)
(root/'browser.json').write_text(json.dumps({'origin':config['origin'],'admin':{'username':'native-review-admin','password':password},'cases':cases,'private_root':str(root),'evidence':config['evidence']}))
def enqueue(name,index,duration):
    wid=cases['encode']['workers'][index]['worker_id'];identity=uuid4().hex
    with owner.connection() as d:d.execute('INSERT INTO start_partial_jobs(id,target_worker_id,attempt_id,duration_seconds) VALUES(%s,%s,%s,%s)',(identity,wid,uuid4().hex,duration))
    job_ids[name]=identity
app.mount('/',StaticFiles(directory=config['web_dist'],html=True));server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config['port'],access_log=False,log_level='warning'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
(root/'ready.json').write_text(json.dumps({'ready':True}))
last=None
try:
    while not (root/'stop').exists():
        if (root/'command.json').exists():
            command=json.loads((root/'command.json').read_text())
            if command['id']!=last:
                kind=command['kind'];group=command.get('group')
                if kind=='pause':pause=True
                elif kind=='resume':pause=False
                elif kind=='hide_ack':
                    original=next((root/group/'receipts').glob('*.json'));held=original.with_suffix('.held');original.rename(held);hidden[group]=(original,held)
                elif kind=='restore_ack':
                    original,held=hidden.pop(group);held.rename(original)
                elif kind=='new_boot':
                    cid=cases[group]['workers'][0]['target_id'];docker('kill','--signal','SIGTERM',cid);docker('wait',cid);docker('start',cid)
                elif kind=='initial_jobs':enqueue('keep_first',0,6);enqueue('removed_current',1,20)
                elif kind=='followup_jobs':enqueue('keep_next',0,4);enqueue('removed_next',1,2)
                else:raise ValueError('unknown_fixture_command')
                last=command['id'];(root/'command-result.json').write_text(json.dumps({'id':last,'done':True}))
        beat()
        if not pause:
            for group in cases:one(group)
        with owner.connection() as d:jobs=[dict(v) for v in d.execute('SELECT id,target_worker_id,worker_id,worker_boot,state,duration_seconds,started_at,completed_at,claim_count,sha256,octet_length(artifact) AS bytes FROM start_partial_jobs ORDER BY number').fetchall()]
        (root/'jobs.json').write_text(json.dumps({'ids':job_ids,'jobs':jobs,'faults':faults,'host_paused':pause},default=str))
        for job in jobs:
            if job['state']=='completed' and not (artifacts/(job['id']+'.mp4')).exists():
                with owner.connection() as d:data=d.execute('SELECT artifact FROM start_partial_jobs WHERE id=%s',(job['id'],)).fetchone()['artifact']
                (artifacts/(job['id']+'.mp4')).write_bytes(bytes(data))
        time.sleep(.15)
finally:
    server.should_exit=True;thread.join(timeout=5)
    for cid in created:
        if physical(cid)['Running']:docker('kill','--signal','SIGTERM',cid);docker('wait',cid)
        docker('rm',cid)
    client.close()
