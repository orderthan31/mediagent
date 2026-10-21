"""New boundary only: a partial recovery cannot certify a replaced/unready survivor."""
import secrets
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from test_control_recovery import actor
from video_service.agent_control import Target
from video_service.control_ack_receipts import AckReceipts
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_journal import ControlJournal
from video_service.postgres.control_recovery import ControlRecovery


@pytest.mark.parametrize('changed',['boot','unknown','missing_baseline'])
def test_partial_recovery_keeps_block_when_survivor_generation_or_health_changed(actor,tmp_path,changed):
    db,admin=actor;store=RemoteControl(db);group='partial_'+uuid4().hex[:8];ids=[uuid4().hex,uuid4().hex]
    before=[{'id':wid,'target_id':c*64,'image_id':'sha256:'+'f'*64,'running':True,'state':'ready','boot_id':uuid4().hex,'started_at':'2026-01-01T00:00:00Z','restart_policy':'no','exit_code':0,'ticket_id':None,'attempt_id':None} for wid,c in zip(ids,['a','b'])]
    store.provision(group,'c'*64,ids);store.publish(group,'c'*64,before)
    receipt=store.configure(admin,group,revision=0,enabled=True,replicas=1,request_id=uuid4().hex);command=store.claim(group,'c'*64)
    journal=ControlJournal(store);journal.prepare(command,'c'*64,before);action=journal.actions(receipt['request_id'])[0];journal.begin(action['id']);action=journal.actions(receipt['request_id'])[0]
    target=Target('b'*64,'sha256:'+'f'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service',group),('mideagent.worker_id',ids[1])))
    files=AckReceipts(tmp_path,secrets.token_bytes(32));files.record(action,'c'*64,target,{'started_at':before[1]['started_at']})
    after=[{**before[0],**({'boot_id':uuid4().hex} if changed=='boot' else {'state':'unknown'} if changed=='unknown' else {})},{**before[1],'running':False,'state':'stopped','report_state':'stopped','report_received_at':datetime.now(timezone.utc).isoformat()}]
    store.publish(group,'c'*64,after);journal.reconcile(receipt['request_id'],after);recovery=ControlRecovery(store);recovery.publish_evidence(action['id'],files.read(action,'c'*64,target))
    if changed=='missing_baseline':
        with db.connection() as conn:conn.execute('UPDATE remote_control_batches SET baseline=NULL WHERE request_id=%s',(receipt['request_id'],))
    plan=recovery.preview(admin,group)
    assert plan['allowed']==['hold'],'target count alone cannot prove the retained worker continued'
