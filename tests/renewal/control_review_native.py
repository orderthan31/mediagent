"""Disposable real Docker + PG + authenticated product ASGI recovery journey.

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
owner=Database(config['dsn']);assert urlsplit(config['dsn']).path.startswith('/control_review_');owner.migrate()
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
app=create_app(api_db,allowed_origins=('http://testserver',),secure_cookies=False,remote_control=store,control_recovery=recovery)
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
try:
    for group,fault,abnormal,choice in [('analyze','after_receipt',False,'confirm_observed'),('validate_video','before_signal',False,'hold'),('encode',None,True,'quarantine_failed')]:
        wid=uuid4().hex;name='review-worker-'+uuid4().hex[:8];case=root/group;case.mkdir();key=case/'signing.key';key.write_bytes(secrets.token_bytes(32))
        labels=[('com.docker.compose.project','isolated-admin-recovery'),('com.docker.compose.service',group),('mideagent.worker_id',wid),('mideagent.scope','isolated-admin-recovery')]
        envfile=case/'worker.env';envfile.write_text('\n'.join(['MIDEAGENT_CONTROL_DISPOSABLE=1','REVIEW_WORKER_ID='+wid,'REVIEW_ROLE='+group,'REVIEW_REPORT_DSN='+dsn('report','review-pg',5432),'REVIEW_ABNORMAL='+('1' if abnormal else '0')]))
        args=['create','--name',name,'--network',config['network'],'--restart','no','--read-only','--tmpfs','/tmp:rw,nosuid,size=32m','--env-file',str(envfile),'--mount','type=bind,source='+str(worker_source)+',target=/fixture/worker.py,readonly','--entrypoint','python']
        for k,v in labels:args+=['--label',k+'='+v]
        cid=docker(*args,image,'/fixture/worker.py');created.append(cid);docker('start',cid)
        host_config={'scope':config['scope'],'group':group,'worker_id':wid,'target_id':cid,'image_id':image,'labels':labels,'dsn':dsn('host'),'docker_context':context,'fault':None,'receipts':str(case/'receipts'),'key_file':str(key),'call_log':str(case/'native-calls.jsonl')}
        path=case/'host.json';path.write_text(json.dumps(host_config))
        for _ in range(35):
            step(path)
            state=store.get(group)
            if state['state']=='ready':break
            time.sleep(.2)
        assert state['state']=='ready'
        boot=state['workers'][0]['boot_id'];endpoint='/api/admin/agents/'+group+'/recovery';request_id=uuid4().hex
        admitted=client.put('/api/admin/agents/'+group+'/configuration',json={'revision':0,'enabled':False,'replicas':0,'request_id':request_id},headers=headers);assert admitted.status_code==200
        host_config['fault']=fault;path.write_text(json.dumps(host_config));step(path,23 if fault=='after_receipt' else 24 if fault=='before_signal' else 0)
        host_config['fault']=None;path.write_text(json.dumps(host_config))
        if fault!='before_signal':
            for _ in range(40):
                if not physical(cid)['Running']:break
                time.sleep(.1)
        step(path)
        preview=client.post(endpoint+'/preview',json={},headers=headers);assert preview.status_code==200
        plan=preview.json();assert choice in plan['allowed']
        assert plan['context']['request']['request_id']==request_id and plan['context']['actions'][0]['before_boot_id']==boot
        if choice=='hold':
            assert plan['allowed']==['hold']
            denied=client.post(endpoint+'/decisions',json={'plan_id':plan['id'],'decision_id':uuid4().hex,'choice':'confirm_observed','reason':'ACK 근거 없는 해제를 시도하면 거부되어야 함'},headers=headers);assert denied.status_code==409
        decision_id=uuid4().hex;body={'plan_id':plan['id'],'decision_id':decision_id,'choice':choice,'reason':'원래 요청, 고정 대상, boot, 발행 기록과 최신 관측을 대조하여 판단함'}
        admitted=client.post(endpoint+'/decisions',json=body,headers=headers);assert admitted.status_code==200 and admitted.json()['result'] is None
        assert store.get(group)['control']['phase']=='unknown'
        assert client.post(endpoint+'/decisions',json=body,headers=headers).status_code==200
        step(path)
        status=client.get(endpoint).json();outcome=status['history'][0]['result']['outcome']
        assert outcome=={'hold':'held','confirm_observed':'observed_completed','quarantine_failed':'failed_quarantined'}[choice]
        if choice=='quarantine_failed':
            current=store.get(group);assert not current['manageable'] and status['quarantined']
            refused=client.put('/api/admin/agents/'+group+'/configuration',json={'revision':current['revision'],'enabled':True,'replicas':1,'request_id':uuid4().hex},headers=headers);assert refused.status_code==409
        with owner.connection() as db:
            action=dict(db.execute('SELECT id,worker_id,phase,issue_count,before_boot_id FROM remote_control_actions WHERE request_id=%s',(request_id,)).fetchone())
            assert action['issue_count']==1
        calls=[json.loads(s) for s in Path(host_config['call_log']).read_text().splitlines()] if Path(host_config['call_log']).exists() else []
        assert len(calls)==(0 if fault=='before_signal' else 1)
        results.append({'group':group,'worker_id':wid,'boot_id':boot,'request_id':request_id,'fault':fault,'native_worker_exit':physical(cid)['ExitCode'],'allowed':plan['allowed'],'decision_id':decision_id,'outcome':outcome,'original_action':action,'native_mutation_calls':calls,'history':status['history']})
        if physical(cid)['Running']:docker('kill','--signal','SIGTERM',cid)
        docker('wait',cid);docker('rm',cid);created.remove(cid)
    denials={}
    probes={'api_native_evidence_write':(dsn('api'),'UPDATE remote_control_ack_evidence SET valid=false WHERE false'),'api_completion_write':(dsn('api'),"UPDATE remote_control_requests SET phase='succeeded' WHERE false"),'api_observation_write':(dsn('api'),'UPDATE remote_control_groups SET observation_revision=0 WHERE false'),'api_result_write':(dsn('api'),'DELETE FROM remote_control_review_results WHERE false'),'host_password_read':(dsn('host'),'SELECT password_hash FROM accounts LIMIT 1')}
    for name,(connection,query) in probes.items():
        try:
            with psycopg.connect(connection) as db:db.execute(query)
        except psycopg.errors.InsufficientPrivilege:denials[name]=True
        else:raise AssertionError('privilege_boundary_failed_'+name)
    Path(config['result']).write_text(json.dumps({'scope':'disposable Docker / direct-PG telemetry / authenticated product ASGI; not MQ or ticket test','cases':results,'privilege_denials':denials,'api_has_no_docker_adapter':True,'recovery_native_mutations':0},ensure_ascii=False,indent=2))
    print(json.dumps({'cases':len(results),'outcomes':[r['outcome'] for r in results],'privilege_denials':denials,'recovery_native_mutations':0}))
finally:
    for cid in created:
        if physical(cid)['Running']:docker('kill','--signal','SIGTERM',cid);docker('wait',cid)
        docker('rm',cid)
    client.close()
