"""Nonblocking lifecycle signalling: work may drain well beyond CLI deadlines."""
import importlib.util
import json

import pytest
from video_service.agent_control import ControlError, Target


def adapter(*,restart='no'):
    assert importlib.util.find_spec('video_service.durable_control'), 'nonblocking lifecycle adapter missing'
    from video_service.durable_control import SignalControl
    target=Target('a'*64,'sha256:'+'b'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service','encode')))
    calls=[]
    def cli(args):
        calls.append(args)
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':target.container_id,'Image':target.image_id,'Config':{'Labels':dict(target.labels)},'HostConfig':{'RestartPolicy':{'Name':restart}},'State':{'Running':True,'Status':'running','Paused':False,'Dead':False,'ExitCode':0,'StartedAt':'2026-01-01T00:00:00Z'}}])
        assert args[:2]!=['container','stop'], 'must not block the controller on a long drain'
        return ''
    return SignalControl({'encode':(target,)},runner=cli),calls


def test_cooperative_signal_returns_without_waiting_for_job_completion():
    control,calls=adapter();control.signal('encode',0,'stop')
    assert [c for c in calls if c[1]!='inspect']==[['container','kill','--signal','SIGTERM','a'*64]]
    assert control.details('encode')['instances'][0]['running'], 'signal receipt is not stopped proof'


def test_restart_policy_cannot_undo_a_signal_only_stop():
    control,calls=adapter(restart='unless-stopped')
    with pytest.raises(ControlError,match='signal_control_requires_no_restart_policy'):
        control.signal('encode',0,'stop')
    assert all(c[1]=='inspect' for c in calls)
