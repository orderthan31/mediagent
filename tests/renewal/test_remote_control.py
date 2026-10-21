"""Real disposable PostgreSQL admission tests; no operating control targets."""
import importlib.util
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from video_service.postgres import Database, Conflict
from video_service.postgres.accounts import Accounts


@pytest.fixture(scope='module')
def actors():
    assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE') == '1'
    db = Database(os.environ['MIDEAGENT_CONTROL_TEST_DSN'])
    db.migrate()
    accounts = Accounts(db)
    if accounts.setup_required():
        admin = accounts.create('ctrl_' + uuid4().hex[:12], secrets.token_urlsafe(24), first=True)
    else:
        admin = next(a for a in accounts.list() if a['role']=='admin' and a['active'])
    member = accounts.create('member_' + uuid4().hex[:12], secrets.token_urlsafe(24), actor_id=admin['id'])
    return db, admin['id'], member['id']


def ready_store(actors):
    assert importlib.util.find_spec('video_service.postgres.remote_control'), 'durable remote admission missing'
    from video_service.postgres.remote_control import RemoteControl
    db, admin, member = actors
    store = RemoteControl(db)
    group = 'slot_' + uuid4().hex[:10]
    slots = [uuid4().hex, uuid4().hex]
    contract = 'c' * 64
    store.provision(group, contract, slots)
    store.publish(group, contract, [{'id':s,'running':False,'state':'stopped','received_at':None,'ticket_id':None,'ticket_number':None} for s in slots])
    return store, group, contract, admin, member


def test_admin_admission_is_idempotent_cas_and_no_pending_overwrite(actors):
    store, group, contract, admin, member = ready_store(actors)
    key = uuid4().hex
    with pytest.raises(PermissionError):
        store.configure(member, group, revision=0, enabled=True, replicas=1, request_id=key)
    first = store.configure(admin, group, revision=0, enabled=True, replicas=1, request_id=key)
    assert first['request_id'] == key
    assert store.configure(admin, group, revision=0, enabled=True, replicas=1, request_id=key) == first
    with pytest.raises(Conflict):
        store.configure(admin, group, revision=0, enabled=True, replicas=2, request_id=key)
    with pytest.raises(Conflict):
        store.configure(admin, group, revision=1, enabled=False, replicas=0, request_id=uuid4().hex)
    assert store.get(group)['revision'] == 1
    with store.database.connection() as db:
        assert db.execute('SELECT count(*) n FROM remote_control_requests WHERE agent_id=%s',(group,)).fetchone()['n'] == 1


def test_concurrent_administrators_accept_exactly_one_request(actors):
    store, group, contract, admin, member = ready_store(actors)
    def configure(_):
        try:
            store.configure(admin,group,revision=0,enabled=True,replicas=1,request_id=uuid4().hex)
            return 'accepted'
        except Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(configure,range(2)))
    assert sorted(outcomes)==['accepted','conflict']


def test_host_controller_claims_once_and_requires_inspect_readback(actors):
    assert importlib.util.find_spec('video_service.control_host'), 'separate host controller missing'
    from video_service.agent_control import DockerControl, Target
    from video_service.control_host import HostControl
    import json
    import time
    db, admin, member = actors
    from video_service.postgres.remote_control import RemoteControl
    store=RemoteControl(db);group='host_'+uuid4().hex[:10];wid=uuid4().hex
    target=Target('a'*64,'sha256:'+'b'*64,(('com.docker.compose.project','fixture'),('com.docker.compose.service',group),('mideagent.worker_id',wid)))
    running=False;mutations=[]
    def cli(args):
        nonlocal running
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':target.container_id,'Image':target.image_id,'Config':{'Labels':dict(target.labels)},'State':{'Running':running,'Status':'running' if running else 'exited','Paused':False,'Dead':False,'StartedAt':'2026-01-01T00:00:00Z'}}])
        mutations.append(args);running=args[1]=='start';return ''
    host=HostControl(store,DockerControl({group:(target,)},runner=cli),{group:[wid]})
    try:
        host.step()
        key=uuid4().hex;store.configure(admin,group,revision=0,enabled=True,replicas=1,request_id=key)
        for _ in range(20):
            host.step()
            if store.get(group)['control']['phase'] is None:break
            time.sleep(.01)
        assert len(mutations)==1
        assert store.get(group)['observed_replicas']==1
        assert store.get(group)['state']=='unknown', 'Running without a new worker report is not ready'
        for _ in range(3):host.step()
        assert len(mutations)==1
    finally:host.close()


def test_all_removed_slots_receive_stop_before_waiting_for_one_to_drain():
    from video_service.agent_control import DockerControl, Target
    import json
    import threading
    labels=(('com.docker.compose.project','fixture'),('com.docker.compose.service','analyze'))
    targets=tuple(Target(c*64,'sha256:'+'c'*64,labels) for c in ['a','b'])
    running={t.container_id:True for t in targets};barrier=threading.Barrier(2)
    def cli(args):
        if args[:2]==['container','inspect']:
            return json.dumps([{'Id':i,'Image':'sha256:'+'c'*64,'Config':{'Labels':dict(labels)},'State':{'Running':running[i],'Status':'running' if running[i] else 'exited','Paused':False,'Dead':False}} for i in args[2:]])
        if args[1]=='stop':
            barrier.wait(timeout=1)
            running[args[-1]]=False
        return ''
    control=DockerControl({'analyze':targets},runner=cli)
    assert control.apply('analyze',0)['running']==0


def test_host_rejects_a_worker_identity_shared_by_two_groups(actors):
    from video_service.agent_control import DockerControl, Target, ControlError
    from video_service.control_host import HostControl
    from video_service.postgres.remote_control import RemoteControl
    db,admin,member=actors
    groups={};slots={};wid=uuid4().hex
    for container in ['d','e']:
        group='identity_'+uuid4().hex[:10]
        labels=(('com.docker.compose.project','fixture'),('com.docker.compose.service',group),('mideagent.worker_id',wid))
        groups[group]=(Target(container*64,'sha256:'+'f'*64,labels),);slots[group]=[wid]
    host=None
    try:
        with pytest.raises(ControlError,match='duplicate_worker_identity'):
            host=HostControl(RemoteControl(db),DockerControl(groups,runner=lambda args: ''),slots)
    finally:
        if host:host.close()


def test_stale_host_and_invalid_count_fail_closed(actors):
    store, group, contract, admin, member = ready_store(actors)
    with store.database.connection() as db:
        db.execute("UPDATE remote_control_groups SET observed_at=now()-interval '60 seconds' WHERE agent_id=%s",(group,))
    assert store.get(group)['manageable'] is False
    with pytest.raises(Conflict):
        store.configure(admin,group,revision=0,enabled=True,replicas=1,request_id=uuid4().hex)
    for count in [True,-1,3]:
        with pytest.raises(ValueError):
            store.configure(admin,group,revision=0,enabled=True,replicas=count,request_id=uuid4().hex)
