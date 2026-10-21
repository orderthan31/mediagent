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
config=json.loads(Path(sys.argv[1]).read_text());assert config['scope']=='isolated-admin-recovery'
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
worker_source=source/'tests/renewal/control_review_worker.py'
def docker(*args):
    p=subprocess.run(['docker','--context',context,*args],capture_output=True,text=True,timeout=40)
    assert p.returncode==0,'fixture_docker_command_failed';return p.stdout.strip()
def physical(cid):return json.loads(docker('inspect',cid))[0]['State']
def step(path,expected=0):
    p=subprocess.run([sys.executable,str(source/'tests/renewal/control_review_host.py'),str(path)],capture_output=True,text=True,timeout=40)
    if p.returncode!=expected:
        (root/'host-failure.log').write_text(p.stdout+p.stderr)
        raise AssertionError('native_host_unexpected_exit_'+str(p.returncode))

from starlette.staticfiles import StaticFiles
from video_service.postgres.worker_telemetry import WorkerTelemetry
import threading,uvicorn
cases={};original_receipts={}
for group,fault,abnormal in [('analyze','after_receipt',False),('validate_video','before_signal',False),('encode',None,True)]:
    wid=uuid4().hex;case=root/group;case.mkdir();key=case/'signing.key';key.write_bytes(secrets.token_bytes(32))
    labels=[('com.docker.compose.project','isolated-admin-recovery-ui'),('com.docker.compose.service',group),('mideagent.worker_id',wid),('mideagent.scope','isolated-admin-recovery-ui')]
    envfile=case/'worker.env';envfile.write_text('\n'.join(['MIDEAGENT_CONTROL_DISPOSABLE=1','REVIEW_WORKER_ID='+wid,'REVIEW_ROLE='+group,'REVIEW_REPORT_DSN='+dsn('report','review-pg',5432),'REVIEW_ABNORMAL='+('1' if abnormal else '0')]))
    args=['create','--name','review-ui-worker-'+uuid4().hex[:8],'--network',config['network'],'--restart','no','--read-only','--tmpfs','/tmp:rw,nosuid,size=32m','--env-file',str(envfile),'--mount','type=bind,source='+str(worker_source)+',target=/fixture/worker.py,readonly','--entrypoint','python']
    for k,v in labels:args+=['--label',k+'='+v]
    cid=docker(*args,image,'/fixture/worker.py');created.append(cid);docker('start',cid)
    hc={'scope':config['scope'],'group':group,'worker_id':wid,'target_id':cid,'image_id':image,'labels':labels,'dsn':dsn('host'),'docker_context':context,'fault':None,'receipts':str(case/'receipts'),'key_file':str(key),'call_log':str(case/'native-calls.jsonl')}
    path=case/'host.json';path.write_text(json.dumps(hc))
    for _ in range(35):
        step(path)
        if store.get(group)['state']=='ready':break
        time.sleep(.2)
    assert store.get(group)['state']=='ready'
    request_id=uuid4().hex
    assert client.put('/api/admin/agents/'+group+'/configuration',json={'revision':0,'enabled':False,'replicas':0,'request_id':request_id},headers=headers).status_code==200
    hc['fault']=fault;path.write_text(json.dumps(hc));step(path,23 if fault=='after_receipt' else 24 if fault=='before_signal' else 0)
    hc['fault']=None;path.write_text(json.dumps(hc))
    if fault!='before_signal':
        for _ in range(40):
            if not physical(cid)['Running']:break
            time.sleep(.1)
    step(path);assert store.get(group)['control']['phase']=='unknown'
    cases[group]={'worker_id':wid,'target_id':cid,'request_id':request_id,'host_config':str(path)}
    if group=='analyze':
        receipt=next((case/'receipts').glob('*.json'));original_receipts[group]=(receipt,receipt.read_bytes())
(root/'browser.json').write_text(json.dumps({'origin':config['origin'],'admin':{'username':'native-review-admin','password':password},'cases':cases,'private_root':str(root),'evidence':config['evidence']}))
app.mount('/',StaticFiles(directory=config['web_dist'],html=True))
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config['port'],access_log=False,log_level='warning'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
(root/'ready.json').write_text(json.dumps({'ready':True,'scope':'actual API/PG and native fixture, no MQ/tickets'}))
paused=False;last_command=None;sink=WorkerTelemetry(owner)
try:
    while not (root/'stop').exists():
        command_file=root/'command.json'
        if command_file.exists():
            command=json.loads(command_file.read_text())
            if command['id']!=last_command:
                kind=command['kind']
                if kind=='pause':paused=True
                elif kind=='resume':paused=False
                elif kind=='stop_validate':
                    cid=cases['validate_video']['target_id'];docker('kill','--signal','SIGTERM',cid);docker('wait',cid)
                elif kind=='tamper_ack':
                    path,data=original_receipts['analyze'];path.write_bytes(data+b'!')
                elif kind=='restore_ack':
                    path,data=original_receipts['analyze'];path.write_bytes(data)
                else:raise ValueError('unknown_private_fixture_command')
                last_command=command['id'];(root/'command-result.json').write_text(json.dumps({'id':last_command,'done':True}))
        sink.beat()
        if not paused:
            for value in cases.values():step(Path(value['host_config']))
        time.sleep(.15)
finally:
    server.should_exit=True;thread.join(timeout=5)
    for cid in created:
        if physical(cid)['Running']:docker('kill','--signal','SIGTERM',cid);docker('wait',cid)
        docker('rm',cid)
    client.close()
