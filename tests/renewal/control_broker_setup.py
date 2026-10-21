"""Fresh disposable broker/S3 bootstrap and least-privilege PG principals only."""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
from pathlib import Path
from urllib.parse import urlsplit
import psycopg
from psycopg import sql
from app.bootstrap import generate
from video_service.postgres import Database
from video_service.worker_telemetry import exchange

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config_path=Path(os.environ['MIDEAGENT_BROKER_CONTROL_CONFIG']);cfg=json.loads(config_path.read_text())
parts=urlsplit(cfg['owner_dsn']);assert parts.hostname=='127.0.0.1' and parts.path.startswith('/control_broker_')
root=Path(cfg['private_root']);assert root.name=='private' and root.parent.name.startswith('broker-control-')
bootstrap=root/'bootstrap'
assert cfg.get('generated_in_isolated_linux') is True and (bootstrap/'api/api.json').is_file()
Database(cfg['owner_dsn']).migrate()

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value,dict) else value)

def db_url(role,host):return f"postgresql://{role['role']}:{role['password']}@{host}:{parts.port if host=='127.0.0.1' else 5432}{parts.path}"

roles={name:{'role':'bc_'+name+'_'+secrets.token_hex(5),'password':secrets.token_urlsafe(32)} for name in ['api','host','collector']}
cfg['pg_roles']=roles
with psycopg.connect(cfg['owner_dsn']) as db:
    for role in roles.values():
        name=sql.Identifier(role['role'])
        db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(name,sql.Literal(role['password'])))
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(name))
    api=sql.Identifier(roles['api']['role']);host=sql.Identifier(roles['host']['role']);collector=sql.Identifier(roles['collector']['role'])
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(api))
    db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(api))
    db.execute(sql.SQL('REVOKE ALL ON remote_control_groups,remote_control_requests,remote_control_reports,remote_control_batches,remote_control_actions,telemetry_observer,worker_observations,worker_observation_events FROM {}').format(api))
    db.execute(sql.SQL('GRANT SELECT ON remote_control_groups,remote_control_requests,telemetry_observer,worker_observations,worker_observation_events TO {}').format(api))
    db.execute(sql.SQL('GRANT UPDATE(revision,enabled,replicas,pending_request) ON remote_control_groups TO {}').format(api))
    db.execute(sql.SQL('GRANT INSERT ON remote_control_requests TO {}').format(api))
    db.execute(sql.SQL('GRANT SELECT,INSERT ON remote_control_groups TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(observed,observed_at,pending_request) ON remote_control_groups TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT ON remote_control_requests,worker_observations,telemetry_observer TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(phase,error_code,updated_at) ON remote_control_requests TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON remote_control_batches,remote_control_actions TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON telemetry_observer,worker_observations,worker_observation_events TO {}').format(collector))
    db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(collector))

defs=json.loads((bootstrap/'broker/definitions.json').read_text());defs.update(exchanges=[],queues=[],bindings=[])
def user(name,password,*,write_to,read_from):
    salt=os.urandom(4)
    defs['users'].append({'name':name,'password_hash':base64.b64encode(salt+hashlib.sha256(salt+password.encode()).digest()).decode(),'hashing_algorithm':'rabbit_password_hashing_sha256','tags':[]})
    defs['permissions'].append({'user':name,'vhost':'/mideagent','configure':'^$','write':write_to,'read':read_from})
    return f'amqps://{name}:{password}@broker:5671/%2Fmideagent'

bindings={};cfg['slots']=[]
for index,role in enumerate(['encode','encode','validate_video']):
    wid=secrets.token_hex(16);folder=bootstrap/'slots'/wid;folder.mkdir(parents=True)
    for old in (bootstrap/'agent'/role).iterdir():
        if old.is_file():shutil.copyfile(old,folder/old.name)
    # Each actual consumer has its own job and status identities.
    command_url=user('c_'+wid,secrets.token_urlsafe(32),write_to=r'^mideagent\.results\.v1$',read_from='^'+re.escape('mideagent.'+role+'.v1')+'$')
    write(folder/'command-url',command_url)
    write(folder/'broker.json',{'namespace':'mideagent','url_file':'/run/bootstrap/command-url','ca_file':'/run/bootstrap/ca.crt'})
    status_exchange=exchange('cpu',role,worker_id=wid)
    status_url=user('s_'+wid,secrets.token_urlsafe(32),write_to='^'+re.escape(status_exchange)+'$',read_from='^$')
    write(folder/'status-url',status_url)
    write(folder/'telemetry.json',{'worker_id':wid,'family':'cpu','role':role,'url_file':'/run/bootstrap/status-url','ca_file':'/run/bootstrap/ca.crt','instance_exchange':True})
    value=json.loads((folder/'objects.json').read_text());value['cache_root']='/cache';write(folder/'objects.json',value)
    defs['exchanges'].append({'name':status_exchange,'vhost':'/mideagent','type':'direct','durable':True,'auto_delete':False,'internal':False,'arguments':{}})
    defs['bindings'].append({'source':status_exchange,'vhost':'/mideagent','destination':'mideagent.telemetry.events.v1','destination_type':'queue','routing_key':'status','arguments':{}})
    bindings[status_exchange]=wid;cfg['slots'].append({'worker_id':wid,'role':role,'folder':str(folder),'controlled':role=='encode'})
queue='mideagent.telemetry.events.v1'
defs['queues'].append({'name':queue,'vhost':'/mideagent','durable':True,'auto_delete':False,'arguments':{'x-message-ttl':15000,'x-max-length':4096}})
collector_url=user('status_reader',secrets.token_urlsafe(32),write_to='^$',read_from='^'+re.escape(queue)+'$')
write(bootstrap/'broker/definitions.json',defs)
collector_root=bootstrap/'collector';collector_root.mkdir()
shutil.copyfile(bootstrap/'api/ca.crt',collector_root/'ca.crt')
write(collector_root/'status-url',collector_url);write(collector_root/'database-dsn',db_url(roles['collector'],'control-pg'))
write(collector_root/'collector.json',{'url_file':'/run/bootstrap/status-url','ca_file':'/run/bootstrap/ca.crt','database_dsn_file':'/run/bootstrap/database-dsn','workers':bindings})
write(bootstrap/'api/database-dsn',db_url(roles['api'],'control-pg'))
for component in ['api','operator']:
    objects=json.loads((bootstrap/component/'objects.json').read_text());objects['cache_root']='/cache';write(bootstrap/component/'objects.json',objects)
api_config=json.loads((bootstrap/'api/api.json').read_text());api_config.update(content_root='/cache',host='0.0.0.0',port=8080,secure_cookies=False,allowed_origins=[cfg['origin']]);write(bootstrap/'api/api.json',api_config)
cfg['bootstrap']=str(bootstrap);cfg['host_dsn']=db_url(roles['host'],'127.0.0.1')
config_path.write_text(json.dumps(cfg))
print(json.dumps({'fresh_bootstrap_generated':True,'bound_worker_identities':len(cfg['slots']),'operating_configuration_used':False}))
