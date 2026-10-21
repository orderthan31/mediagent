"""Durable signal/wait split against explicitly disposable PostgreSQL."""
import importlib.util
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.remote_control import RemoteControl


@pytest.fixture(scope='module')
def actor():
    assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
    dsn=os.environ['MIDEAGENT_JOURNAL_TEST_DSN']
    assert urlsplit(dsn).hostname=='127.0.0.1' and urlsplit(dsn).path.startswith('/control_journal_')
    db=Database(dsn);db.migrate();accounts=Accounts(db)
    admin=(accounts.create('journal-admin',secrets.token_urlsafe(30),first=True) if accounts.setup_required() else next(a for a in accounts.list() if a['role']=='admin'))
    return db,admin['id']


def case(actor):
    assert importlib.util.find_spec('video_service.postgres.control_journal'), 'durable signal journal missing'
    from video_service.postgres.control_journal import ControlJournal
    db,admin=actor;store=RemoteControl(db);group='journal_'+uuid4().hex[:10];slots=[uuid4().hex,uuid4().hex];contract='c'*64
    store.provision(group,contract,slots)
    snapshot=[{'id':s,'running':True,'state':'busy','boot_id':uuid4().hex,'received_at':datetime.now(timezone.utc).isoformat(),'ticket_id':uuid4().hex,'exit_code':0,'started_at':'2026-01-01T00:00:00+00:00','restart_policy':'no'} for s in slots]
    store.publish(group,contract,snapshot)
    request=store.configure(admin,group,revision=0,enabled=False,replicas=0,request_id=uuid4().hex)
    command=store.claim(group,contract)
    return store,ControlJournal(store),group,contract,snapshot,request,command


def test_sent_signals_resume_read_only_after_host_restart_and_long_drain(actor):
    store,journal,group,contract,snapshot,request,command=case(actor)
    journal.prepare(command,contract,snapshot)
    actions=journal.actions(request['request_id']);assert len(actions)==2
    for action in actions:
        assert journal.begin(action['id'])
        journal.sent(action['id'])
    # Time spent draining must never turn into a second signal or forced kill.
    with store.database.connection() as db:
        db.execute("UPDATE remote_control_actions SET updated_at=now()-interval '45 seconds' WHERE request_id=%s",(request['request_id'],))
    assert journal.reconcile(request['request_id'],snapshot) is False
    assert all(not journal.begin(a['id']) for a in actions)
    restarted=type(journal)(store)
    assert restarted.reconcile(request['request_id'],snapshot) is False
    stopped=[{**row,'running':False,'state':'stopped','report_state':'stopped','report_received_at':datetime.now(timezone.utc).isoformat()} for row in snapshot]
    store.publish(group,contract,stopped)
    assert restarted.reconcile(request['request_id'],stopped)
    assert store.get(group)['control']['phase'] is None
    assert all(a['issue_count']==1 and a['phase']=='confirmed' for a in restarted.actions(request['request_id']))


def test_abnormal_worker_exit_is_unknown_not_a_successful_drain(actor):
    store,journal,group,contract,snapshot,request,command=case(actor)
    journal.prepare(command,contract,snapshot)
    for action in journal.actions(request['request_id']):
        assert journal.begin(action['id']);journal.sent(action['id'])
    failed=[{**row,'running':False,'state':'stopped','exit_code':137,'report_state':'stopped','report_received_at':datetime.now(timezone.utc).isoformat()} for row in snapshot]
    store.publish(group,contract,failed)
    assert journal.reconcile(request['request_id'],failed) is False
    assert store.get(group)['control']['phase']=='unknown'
    assert store.get(group)['manageable'] is False


def test_crash_in_issuing_window_never_reissues_or_fabricates_success(actor):
    store,journal,group,contract,snapshot,request,command=case(actor)
    journal.prepare(command,contract,snapshot)
    action=journal.actions(request['request_id'])[0]
    assert journal.begin(action['id'])
    restarted=type(journal)(store)
    stopped=[{**row,'running':False,'state':'stopped','report_state':'stopped','report_received_at':datetime.now(timezone.utc).isoformat()} for row in snapshot]
    store.publish(group,contract,stopped)
    assert restarted.reconcile(request['request_id'],stopped) is False
    assert not restarted.begin(action['id'])
    assert store.get(group)['control']['phase']=='unknown'
    assert store.get(group)['manageable'] is False
