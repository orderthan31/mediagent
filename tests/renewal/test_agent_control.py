"""Host-side control primitive tests; no operating Docker targets."""
import importlib
import json
from dataclasses import replace

import pytest


def test_control_reads_back_real_state_and_enforces_fixed_capacity():
    assert importlib.util.find_spec('video_service.agent_control') is not None, 'host adapter missing'
    from video_service.agent_control import DockerControl, Target, ControlError

    image='sha256:'+'c'*64
    labels=(('com.docker.compose.project','isolated-control'),('com.docker.compose.service','encode'))
    targets=(Target('a'*64,image,labels),Target('b'*64,image,labels))
    running={t.container_id:False for t in targets}
    commands=[]
    def run(args):
        commands.append(args)
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':i,'Image':image,'Config':{'Labels':dict(labels)},
                                'State':{'Status':'running' if running[i] else 'exited','Running':running[i],'Paused':False,'Dead':False}}
                               for i in args[2:]])
        running[args[-1]]=args[1]=='start'
        return args[-1]
    control=DockerControl({'encode':targets},runner=run)
    assert control.apply('encode',1)['running']==1
    assert control.apply('encode',2)['running']==2
    assert control.apply('encode',0)['running']==0
    stops=[c for c in commands if c[:2]==['container','stop']]
    assert stops and all(c[2:4]==['--timeout','-1'] for c in stops)
    count=len(commands)
    for bad in [True,-1,3,'2']:
        with pytest.raises(ControlError):control.apply('encode',bad)
    with pytest.raises(ControlError):control.apply('not-registered',0)
    assert len(commands)==count
    # Pin mismatch must fail before touching any target, not just after a start.
    wrong=DockerControl({'encode':(replace(targets[0],image_id='sha256:'+'d'*64),)},runner=run)
    with pytest.raises(ControlError):wrong.apply('encode',1)
    assert all(not v for v in running.values())
