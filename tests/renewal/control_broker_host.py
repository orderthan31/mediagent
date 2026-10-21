"""Fixed-host broker control for an explicit disposable fixture only."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from video_service.agent_control import Target
from video_service.durable_control import SignalControl, BrokerReports, DurableHost
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
cfg=json.loads(Path(os.environ['MIDEAGENT_BROKER_CONTROL_CONFIG']).read_text())
assert cfg['project'].startswith('isolated-broker-control-')
assert urlsplit(cfg['host_dsn']).hostname=='127.0.0.1' and urlsplit(cfg['host_dsn']).path.startswith('/control_broker_')
targets=[];slots=[]
for row in cfg['targets']:
    assert row['labels']['com.docker.compose.project']==cfg['project'] and row['labels']['com.docker.compose.service']=='encode'
    targets.append(Target(row['container_id'],row['image_id'],tuple(row['labels'].items())));slots.append(row['worker_id'])
db=Database(cfg['host_dsn']);store=RemoteControl(db)
host=DurableHost(store,SignalControl({'encode':tuple(targets)},context=cfg['docker_context']),{'encode':slots},BrokerReports(db,{'encode':('cpu','encode')}))
try:
    while not Path(cfg['host_stop_file']).exists():host.step();time.sleep(.2)
finally:host.close()
