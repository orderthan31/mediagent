"""Explicit host-only runner for disposable fixed-target acceptance."""
import json
import os
import time
from pathlib import Path

from video_service.agent_control import DockerControl, Target
from video_service.control_host import HostControl
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config=json.loads(Path(os.environ['MIDEAGENT_CONTROL_HOST_CONFIG']).read_text())
assert config['project'].startswith('isolated-product-control-')
targets=[];slots=[]
for row in config['targets']:
    assert row['labels']['com.docker.compose.project']==config['project']
    assert row['labels']['com.docker.compose.service']=='analyze'
    target=Target(row['container_id'],row['image_id'],tuple(row['labels'].items()))
    targets.append(target);slots.append(row['worker_id'])
store=RemoteControl(Database(config['dsn']))
host=HostControl(store,DockerControl({'analyze':tuple(targets)},context=config['docker_context']),{'analyze':slots})
try:
    while not Path(config['stop_file']).exists():
        host.step();time.sleep(.2)
finally:host.close()
