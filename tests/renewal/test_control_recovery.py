"""Admin recovery uses real disposable PG; native command cases are separate."""
import importlib.util
import os
import secrets
from datetime import datetime,timezone
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from video_service.agent_control import Target
from video_service.postgres import Database,Conflict
from video_service.postgres.accounts import Accounts
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.control_journal import ControlJournal
from video_service.control_ack_receipts import AckReceipts


@pytest.fixture(scope='module')
def actor():
    assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
    dsn=os.environ['MIDEAGENT_REVIEW_TEST_DSN'];assert urlsplit(dsn).hostname=='127.0.0.1' and urlsplit(dsn).path.startswith('/control_review_')
    db=Database(dsn);db.migrate();accounts=Accounts(db)
    admin=accounts.create('review-admin',secrets.token_urlsafe(30),first=True) if accounts.setup_required() else next(a for a in accounts.list() if a['role']=='admin')
    return db,admin['id']


def unknown_case(actor,tmp_path,*,receipt=True,exit_code=0):
    assert importlib.util.find_spec('video_service.postgres.control_recovery'),'admin recovery missing'
    from video_service.postgres.control_recovery import ControlRecovery
    db,admin=actor;store=RemoteControl(db);group='review_'+uuid4().hex[:10];worker=uuid4().hex;boot=uuid4().hex;contract='c'*64
    store.provision(group,contract,[worker])
    before=[{'id':worker,'target_id':'a'*64,'image_id':'sha256:'+'b'*64,'running':True,'state':'ready','boot_id':boot,'received_at':datetime.now(timezone.utc).isoformat(),'ticket_id':None,'attempt_id':None,'exit_code':0,'started_at':'2026-01-01T00:00:00Z','restart_policy':'no'}]
    store.publish(group,contract,before)
    request=store.configure(admin,group,revision=0,enabled=False,replicas=0,request_id=uuid4().hex);command=store.claim(group,contract)
    journal=ControlJournal(store);journal.prepare(command,contract,before);action=journal.actions(request['request_id'])[0];journal.begin(action['id']);action=journal.actions(request['request_id'])[0]
    stopped=[{**before[0],'running':False,'state':'stopped','exit_code':exit_code,'report_state':'stopped' if exit_code==0 else 'ready','report_received_at':datetime.now(timezone.utc).isoformat()}]
    store.publish(group,contract,stopped);journal.reconcile(request['request_id'],stopped)
    recovery=ControlRecovery(store)
    if receipt:
        target=Target('a'*64,'sha256:'+'b'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service',group)))
        receipts=AckReceipts(tmp_path,secrets.token_bytes(32));receipts.record(action,contract,target,{'started_at':before[0]['started_at']})
        recovery.publish_evidence(action['id'],receipts.read(action,contract,target))
    return store,recovery,admin,group,action,stopped


def test_admin_decision_is_queued_then_host_verified_without_rewriting_issue_history(actor,tmp_path):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path)
    plan=recovery.preview(admin,group)
    assert 'confirm_observed' in plan['allowed']
    decision=recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='confirm_observed',reason='원래 대상과 boot, ACK 자료 및 정상 종료 관측을 대조함')
    assert decision['result'] is None
    assert store.get(group)['control']['phase']=='unknown', 'API must not mark completion'
    recovery.apply_pending(group)
    result=recovery.status(group)
    assert result['history'][0]['result']['outcome']=='observed_completed'
    assert result['history'][0]['reason'].startswith('원래 대상')
    assert store.get(group)['control']['phase'] is None
    with store.database.connection() as db:
        original=db.execute('SELECT phase,issue_count FROM remote_control_actions WHERE id=%s',(action['id'],)).fetchone()
        assert original=={'phase':'issuing','issue_count':1}
        assert db.execute('SELECT phase FROM remote_control_requests WHERE request_id=%s',(action['request_id'],)).fetchone()['phase']=='reviewed_completed'


def test_missing_ack_cannot_be_released_and_hold_keeps_original_unknown(actor,tmp_path):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path,receipt=False)
    plan=recovery.preview(admin,group)
    assert plan['allowed']==['hold']
    with pytest.raises(Conflict):recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='confirm_observed',reason='근거 없이 해제하지 않음')
    recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='hold',reason='ACK 자료가 없어 원래 요청과 대상 봉쇄를 유지함')
    recovery.apply_pending(group)
    assert store.get(group)['control']['phase']=='unknown'
    assert recovery.status(group)['history'][0]['result']['outcome']=='held'


def test_observation_aba_invalidates_an_admin_plan(actor,tmp_path):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path)
    plan=recovery.preview(admin,group)
    store.publish(group,'c'*64,[{**stopped[0],'state':'unknown'}])
    store.publish(group,'c'*64,stopped)
    with pytest.raises(Conflict):recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='confirm_observed',reason='중간 관측 변경도 무시하지 않음')


def test_abnormal_exit_is_failed_and_quarantined_not_success_or_restart(actor,tmp_path):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path,exit_code=7)
    plan=recovery.preview(admin,group);assert 'confirm_observed' not in plan['allowed']
    recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='quarantine_failed',reason='같은 boot 비정상 종료를 확인하여 격리하고 작업 성공으로 처리하지 않음')
    recovery.apply_pending(group)
    assert recovery.status(group)['history'][0]['result']['outcome']=='failed_quarantined'
    current=store.get(group)
    assert not current['manageable']
    with pytest.raises(Conflict):store.configure(admin,group,revision=current['revision'],enabled=True,replicas=1,request_id=uuid4().hex)


def test_host_rechecks_after_admission_and_decision_is_idempotent(actor,tmp_path):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path)
    plan=recovery.preview(admin,group);decision_id=uuid4().hex
    args={'plan_id':plan['id'],'decision_id':decision_id,'choice':'confirm_observed','reason':'호스트도 최신 관측을 다시 검증해야 함'}
    first=recovery.submit(admin,group,**args)
    assert recovery.submit(admin,group,**args)==first
    with pytest.raises(Conflict):recovery.submit(admin,group,**{**args,'reason':'같은 식별자로 다른 판단은 거부함'})
    with pytest.raises(Conflict):recovery.submit(admin,group,**{**args,'decision_id':uuid4().hex})
    store.publish(group,'c'*64,[{**stopped[0],'boot_id':uuid4().hex}])
    recovery.apply_pending(group)
    assert recovery.status(group)['history'][0]['result']['outcome']=='rejected_stale'
    assert store.get(group)['control']['phase']=='unknown'


@pytest.mark.parametrize('seconds',[-20,20])
def test_recovery_rejects_stale_or_future_host_observation(actor,tmp_path,seconds):
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path)
    with store.database.connection() as db:db.execute("UPDATE remote_control_groups SET observed_at=now()+make_interval(secs=>%s) WHERE agent_id=%s",(seconds,group))
    with pytest.raises(Conflict):recovery.preview(admin,group)


def test_simultaneous_decisions_accept_one_and_preserve_both_contexts(actor,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store,recovery,admin,group,action,stopped=unknown_case(actor,tmp_path)
    plans=[recovery.preview(admin,group) for _ in range(2)];barrier=Barrier(2)
    def submit(plan):
        barrier.wait()
        try:
            recovery.submit(admin,group,plan_id=plan['id'],decision_id=uuid4().hex,choice='confirm_observed',reason='같은 원래 요청에 대한 동시 관리자 판단 시험')
            return 'accepted'
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,plans))
    assert sorted(results)==['accepted','conflict']
    assert len(recovery.status(group)['history'])==1
