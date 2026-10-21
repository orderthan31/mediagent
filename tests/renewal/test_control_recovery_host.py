"""PG + controlled native boundary: crash after durable ACK, before SQL ACK."""
import json
import secrets
from uuid import uuid4
import pytest
from test_control_recovery import actor
from video_service.agent_control import Target
from video_service.durable_control import SignalControl,DurableHost,BrokerReports
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_recovery import ControlRecovery
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter,exchange
from video_service.control_ack_receipts import AckReceipts


def test_host_restart_does_not_resignal_and_admin_confirms_with_native_ack_proof(actor,tmp_path):
    db,admin=actor;group='receipt_'+uuid4().hex[:8];wid=uuid4().hex;running=True;signals=[]
    target=Target('a'*64,'sha256:'+'f'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service',group),('mideagent.worker_id',wid)))
    sink=WorkerTelemetry(db);sink.beat();reporter=WorkerReporter(wid,'cpu','encode',lambda report:sink.accept(report,exchange('cpu','encode'),expected_worker_id=wid));reporter.emit('ready')
    def cli(args):
        if args[:2]==['container','inspect']:return json.dumps([{'Id':target.container_id,'Image':target.image_id,'Config':{'Labels':dict(target.labels)},'HostConfig':{'RestartPolicy':{'Name':'no'}},'State':{'Running':running,'Status':'running' if running else 'exited','Paused':False,'Dead':False,'ExitCode':0,'StartedAt':'2026-01-01T00:00:00Z'}}])
        signals.append(args);return ''
    class InterruptAfterReceipt(AckReceipts):
        def record(self,*args):super().record(*args);raise SystemExit('fixture_pre_sql_ack_crash')
    key=secrets.token_bytes(32);store=RemoteControl(db);recovery=ControlRecovery(store);adapter=SignalControl({group:(target,)},runner=cli)
    first=DurableHost(store,adapter,{group:[wid]},BrokerReports(db,{group:('cpu','encode')}),receipts=InterruptAfterReceipt(tmp_path,key),recovery=recovery)
    try:
        first.step();request=store.configure(admin,group,revision=0,enabled=False,replicas=0,request_id=uuid4().hex)
        with pytest.raises(SystemExit):first.step()
    finally:first.close()
    assert len(signals)==1
    second=DurableHost(store,adapter,{group:[wid]},BrokerReports(db,{group:('cpu','encode')}),receipts=AckReceipts(tmp_path,key),recovery=recovery)
    try:
        reporter.emit('stopped');running=False;second.step()
        assert store.get(group)['control']['phase']=='unknown'
        plan=recovery.preview(admin,group)
        assert plan['context']['targets']==[{'worker_id':wid,'target_id':target.container_id,'image_id':target.image_id}]
        recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='confirm_observed',reason='실제 ACK 자료와 같은 boot 정상 종료 관측을 대조함')
        second.step()
        assert recovery.status(group)['history'][0]['result']['outcome']=='observed_completed'
        assert len(signals)==1
        assert second.journal.actions(request['request_id'])[0]['phase']=='issuing'
    finally:second.close()


def test_noop_signal_cannot_claim_a_native_ack():
    target=Target('a'*64,'sha256:'+'f'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service','noop')))
    calls=[]
    def cli(args):
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':target.container_id,'Image':target.image_id,'Config':{'Labels':dict(target.labels)},'HostConfig':{'RestartPolicy':{'Name':'no'}},'State':{'Running':False,'Status':'exited','Paused':False,'Dead':False,'ExitCode':0,'StartedAt':'2026-01-01T00:00:00Z'}}])
        calls.append(args);return ''
    adapter=SignalControl({'noop':(target,)},runner=cli)
    assert adapter.signal('noop',0,'stop') is False
    assert calls==[]
