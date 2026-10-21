"""Real PG + controlled Docker boundary; live MQ/product acceptance is separate."""
import importlib
import json
from uuid import uuid4
import pytest
from test_control_journal import actor
from video_service.agent_control import Target, ControlError
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter, exchange


def test_new_host_observes_existing_sent_drain_without_repeating_signals(actor):
    module=importlib.import_module('video_service.durable_control')
    assert hasattr(module,'DurableHost'),'durable broker host missing'
    db,admin=actor;group='host_'+uuid4().hex[:10];slots=[uuid4().hex,uuid4().hex];running={w:True for w in slots};signals=[]
    targets=tuple(Target(c*64,'sha256:'+'f'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service',group),('mideagent.worker_id',w))) for c,w in zip(['a','b'],slots))
    sink=WorkerTelemetry(db);sink.beat();reporters={}
    for wid in slots:
        send=lambda report,wid=wid:sink.accept(report,exchange('cpu','encode'),expected_worker_id=wid)
        reporters[wid]=WorkerReporter(wid,'cpu','encode',send);reporters[wid].emit('ready')
    def cli(args):
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':t.container_id,'Image':t.image_id,'Config':{'Labels':dict(t.labels)},'HostConfig':{'RestartPolicy':{'Name':'no'}},'State':{'Running':running[w],'Status':'running' if running[w] else 'exited','Paused':False,'Dead':False,'ExitCode':0,'StartedAt':'2026-01-01T00:00:00Z'}} for t,w in zip(targets,slots)])
        signals.append(args);assert args[1]=='kill';return ''
    store=RemoteControl(db);control=module.SignalControl({group:targets},runner=cli);profiles={group:('cpu','encode')}
    first=module.DurableHost(store,control,{group:slots},module.BrokerReports(db,profiles))
    second=None
    try:
        first.step()
        request=store.configure(admin,group,revision=0,enabled=False,replicas=0,request_id=uuid4().hex)
        first.step();assert len(signals)==2
        with pytest.raises(ControlError,match='control_host_already_owned'):
            module.DurableHost(store,control,{group:slots},module.BrokerReports(db,profiles))
        first.close();first=None
        with db.connection() as conn:conn.execute("UPDATE remote_control_groups SET observed_at=now()-interval '20 seconds' WHERE agent_id=%s",(group,))
        assert store.get(group)['control']['phase']=='unknown'
        second=module.DurableHost(store,control,{group:slots},module.BrokerReports(db,profiles))
        second.step();assert len(signals)==2
        for wid in slots:reporters[wid].emit('stopped');running[wid]=False
        second.step()
        assert store.get(group)['control']['phase'] is None
        assert store.get(group)['observed_replicas']==0
        assert len(signals)==2
        assert all(a['issue_count']==1 for a in second.journal.actions(request['request_id']))
    finally:
        if first:first.close()
        if second:second.close()
