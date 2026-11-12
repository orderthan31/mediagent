"""Actual admission/claim/controller source contracts; fake DB, no engine/provider."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_start_queue import FakeDatabase, OWNER, CONSENT, enroll
from test_start_queue_fleet import fleet_case as fleet_case
from video_service.canonical import digest
from video_service.agent_protocol import CPU_AGENTS
from video_service.content_store import ContentStore
from video_service.start_queue_policy import claim_digest, QueueConflict

ROOT = Path(__file__).resolve().parents[2]


def execution_methods():
    path = ROOT / 'apps/orchestrator/mideagent_orchestrator/execution.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf8')).body if isinstance(n, ast.ClassDef) and n.name == 'Execution')
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {'admit', 'claim_next', '_queue_start_ready_in'}]
    ns = dict(__name__='mideagent_orchestrator.execution', __package__='mideagent_orchestrator',
              digest=digest, uuid4=uuid4, request_id=lambda x:x, resource_id=lambda x:x,
              Conflict=ValueError, TERMINAL={'completed','failed','skipped','blocked','cancelled'},
              spec=lambda *args: {'inputs':{},'optional_inputs':[]}, CPU_AGENTS=CPU_AGENTS, CONTROL=set())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    return ns


class AdmissionDB(FakeDatabase):
    @contextmanager
    def connection(self):
        jobs, claims = deepcopy(self.jobs), deepcopy(self.claims)
        try:
            with super().connection() as db:
                yield db
        except Exception:
            self.jobs, self.claims = jobs, claims
            raise

    def execute(self, sql, params=()):
        if 'request_id=%s' in sql and 'FROM execution_claims' in sql:
            rows = [r for r in self.claims.values() if r.get('request_id') == params[1]]
        elif 'FROM execution_consents' in sql:
            rows = [dict(valid=True, consumed_at=None, plan_sha256='plan')]
        elif sql.startswith('INSERT INTO execution_claims'):
            owner, job_id, claim, consent, generation, nonce, sha = params
            self.claims[claim] = dict(job_id=job_id,claim_id=claim,consent_id=consent,claim_generation=generation,
                                      request_id=nonce,request_sha256=sha)
            rows=[]
        elif sql.startswith('UPDATE execution_consents'):
            rows=[]
        elif sql.startswith("UPDATE jobs SET status='waiting'"):
            claim, owner, id=params
            self.jobs[id].update(active_claim_id=claim,status='waiting')
            rows=[self.jobs[id]]
        elif sql.startswith('UPDATE jobs SET status=CASE'):
            rows=[]
        else:
            return super().execute(sql, params)
        self.calls.append((sql,params))
        return SimpleNamespace(fetchall=lambda:deepcopy(rows),fetchone=lambda:deepcopy(rows[0]) if rows else None)


@pytest.fixture
def case(tmp_path,monkeypatch):
    from mideagent_orchestrator.start_queue import StartQueue
    db=AdmissionDB()
    state=dict(capture=0,reserve=0,enroll=0)
    class Review:
        def __init__(self, runtime): pass
        def capture_in(self, conn, job): state['capture']+=1; return False
    class Pool:
        @staticmethod
        def enroll_in(conn,job): state['enroll']+=1
        @staticmethod
        def ready_in(conn,job,node): return job['id'] not in runtime.capacity_unavailable
        @staticmethod
        def can_start_in(conn,job,node): return job['id'] not in runtime.capacity_unavailable
        @staticmethod
        def assigned_in(*args): pass
    monkeypatch.setitem(sys.modules,'video_service.postgres.subtitle_tracks',SimpleNamespace(SubtitleTracks=lambda runtime:SimpleNamespace(preflight=lambda *args:None)))
    monkeypatch.setitem(sys.modules,'video_service.postgres.job_processing_review',SimpleNamespace(JobProcessingReview=Review))
    monkeypatch.setitem(sys.modules,'mideagent_orchestrator.agent_pool',SimpleNamespace(AgentPool=Pool))
    monkeypatch.setitem(sys.modules,'mideagent_orchestrator.workflow',SimpleNamespace(scope_snapshot=lambda snapshot:None))
    runtime=SimpleNamespace(database=db,store=ContentStore(tmp_path),fleet=None,capacity_unavailable=set(),
                            _preflight_cpu_inputs=lambda *args:None,
                            _view=lambda conn,job:deepcopy(job),
                            _plan=lambda *args:dict(ready=True,token='plan'),
                            _ready_agent_tools=lambda *args:None,
                            _queue_start_ready_in=lambda *args:True,
                            _execution_reasons=lambda *args:[],
                            _queue_start_reasons_in=lambda *args:[],
                            _checked_input=lambda *args:None,
                            _write_outbox=lambda *args:None)
    def getjob(conn,owner,id,lock=False):
        db.calls.append(('JOB LOCK' if lock else 'JOB READ',(owner,id)))
        return deepcopy(db.jobs[id])
    runtime._job=getjob
    runtime._runs=lambda conn,owner,id:deepcopy(db.jobs[id].get('runs',[]))
    def insert(conn,job,node,inputs,status):
        state['reserve']+=1
        row=dict(id=uuid4().hex,node_id=node['id'],status=status)
        db.jobs[job['id']].setdefault('runs',[]).append(row)
        db.jobs[job['id']]['started']=True
        return row,dict(protocol_version=1,run_id=job['id'],attempt_id=row['id'])
    runtime._insert_run=insert
    methods=execution_methods()
    runtime.admit=lambda *args:methods['admit'](runtime,*args)
    runtime.claim_next=lambda *args:methods['claim_next'](runtime,*args)
    return runtime,StartQueue(runtime),db,state


def job(db,number,**kwargs):
    value=db.add(number,**kwargs)
    value['snapshot']={'definition':{'nodes':[dict(id='first',type='analyze',options={})],'edges':[]}}
    return value


def test_actual_first_reservation_pause_order_descendants_and_lock_order(case):
    runtime,queue,db,state=case
    a,b=job(db,40),job(db,41)
    enroll(queue,db,a); enroll(queue,db,b)
    queue.patch(OWNER,2,paused=True)
    db.calls.clear()
    assert runtime.claim_next(OWNER,a['id']) is None
    assert state == dict(capture=0,reserve=0,enroll=0)
    calls=[x[0] for x in db.calls if isinstance(x,tuple)]
    assert 'pg_advisory_xact_lock' in calls[0] and calls[1]=='JOB LOCK'
    queue.patch(OWNER,3,paused=False,order=[b['id']])
    assert runtime.claim_next(OWNER,a['id']) is None
    assert state['reserve']==0
    command=runtime.claim_next(OWNER,b['id'])
    assert command['run_id']==b['id'] and state['reserve']==1
    assert runtime.claim_next(OWNER,a['id'])['run_id']==a['id']
    queue.patch(OWNER,4,paused=True)
    db.jobs[b['id']]['runs'][0]['status']='completed'
    db.jobs[b['id']]['snapshot']['definition']['nodes'].append(dict(id='second',type='analyze',options={}))
    assert runtime.claim_next(OWNER,b['id'])['run_id']==b['id']
    assert state['reserve']==3 and db.jobs[b['id']]['runs'][-1]['node_id']=='second'
    # An existing in-flight/unknown attempt still reaches its native capture fence.
    before=state['capture']
    db.jobs[b['id']]['runs']*=2
    assert runtime.claim_next(OWNER,b['id']) is None
    assert state['capture']==before+1 and state['reserve']==3


def test_actual_admit_enrolls_only_new_claim_and_nonce_replay_never_adopts_old(case):
    runtime,queue,db,state=case
    value=job(db,40,status='draft')
    value['active_claim_id']=None
    db.claims.clear()
    result=runtime.admit(OWNER,value['id'],CONSENT,'explicit-new-start')
    assert queue.get(OWNER)['jobs']==[value['id']]
    claim=db.claims[result['active_claim_id']]
    assert claim['request_sha256']==claim_digest(value['id'],CONSENT)
    revision=queue.get(OWNER)['revision']
    assert runtime.admit(OWNER,value['id'],CONSENT,'explicit-new-start')['active_claim_id']==result['active_claim_id']
    assert queue.get(OWNER)['revision']==revision
    old=job(db,32,new=False)
    db.claims[old['active_claim_id']].update(job_id=old['id'],request_id='old-reply-lost')
    runtime.admit(OWNER,old['id'],CONSENT,'old-reply-lost')
    assert queue.get(OWNER)['jobs']==[value['id']]


def test_queue_progresses_only_enrolled_order_on_resume_without_waiting_completion(case):
    from mideagent_orchestrator.start_queue_progress import advance_start_queue
    runtime,queue,db,state=case
    a,b,old=job(db,40),job(db,41),job(db,32,new=False)
    enroll(queue,db,a); enroll(queue,db,b)
    queue.patch(OWNER,2,paused=True,order=[b['id']])
    dispatched=[]
    def dispatch(owner,id):
        dispatched.append(id)
        return runtime.claim_next(owner,id)
    advance_start_queue(runtime,OWNER,dispatch)
    assert dispatched==[]
    queue.patch(OWNER,3,paused=False)
    advance_start_queue(runtime,OWNER,dispatch)
    assert dispatched==[b['id'],a['id']]
    assert state['reserve']==2 and old['id'] not in dispatched


def test_cross_store_unknown_leaves_only_ignored_orphan_and_reconciles_same_claim(case,monkeypatch):
    from video_service.start_queue_policy import decode_policy
    runtime,queue,db,state=case
    first=job(db,40,status='draft');first['active_claim_id']=None;db.claims.clear()
    write=runtime.store.write_start_queue
    def unknown(owner,raw,token):
        write(owner,raw,token)
        raise OSError('synthetic lost write acknowledgment')
    monkeypatch.setattr(runtime.store,'write_start_queue',unknown)
    with pytest.raises(OSError):
        runtime.admit(OWNER,first['id'],CONSENT,'same-explicit-start')
    orphan=decode_policy(runtime.store.read_start_queue(OWNER)[0],OWNER)['members'][0]
    assert db.claims=={} and queue.get(OWNER)['jobs']==[]
    assert db.jobs[first['id']]['status']=='draft' and state['reserve']==0
    monkeypatch.setattr(runtime.store,'write_start_queue',write)
    result=runtime.admit(OWNER,first['id'],CONSENT,'same-explicit-start')
    assert result['active_claim_id']==orphan['claim_id']
    assert queue.get(OWNER)['jobs']==[first['id']]


def test_new_model_conditions_rechecked_before_first_capture_or_capacity(case):
    runtime,queue,db,state=case
    first=job(db,40)
    enroll(queue,db,first)
    runtime._queue_start_reasons_in=lambda *args:['native model unavailable']
    with pytest.raises(QueueConflict, match='시작 조건'):
        runtime.claim_next(OWNER,first['id'])
    assert state==dict(capture=0,reserve=0,enroll=0)
    assert db.jobs[first['id']]['status']=='waiting'


def test_first_reservation_holds_owner_serialization_until_commit(case,monkeypatch):
    import threading
    runtime,queue,db,state=case
    first=job(db,40)
    enroll(queue,db,first)
    lock, local = threading.RLock(), threading.local()
    commits=[]
    execute=db.execute
    @contextmanager
    def connection():
        local.locks=[]
        try:
            yield db
        finally:
            if local.locks:
                commits.append(threading.current_thread().name)
            for held in reversed(local.locks):held.release()
    def serialized(sql,params=()):
        if 'pg_advisory_xact_lock' in sql:
            lock.acquire();local.locks.append(lock)
        return execute(sql,params)
    monkeypatch.setattr(db,'connection',connection)
    monkeypatch.setattr(db,'execute',serialized)
    reserved, release, changed=threading.Event(),threading.Event(),threading.Event()
    insert=runtime._insert_run
    def hold(*args):
        result=insert(*args);reserved.set()
        assert release.wait(2)
        return result
    runtime._insert_run=hold
    failures=[]
    def start():
        try:runtime.claim_next(OWNER,first['id'])
        except Exception as error:failures.append(error)
    def pause():
        try:queue.patch(OWNER,1,paused=True);changed.set()
        except Exception as error:failures.append(error)
    worker=threading.Thread(target=start,name='first-reservation')
    patch=threading.Thread(target=pause,name='pause-policy')
    worker.start()
    assert reserved.wait(2)
    patch.start()
    try:
        assert not changed.wait(0.05)
    finally:
        release.set();worker.join(3);patch.join(3)
    assert not worker.is_alive() and not patch.is_alive() and failures==[]
    assert commits==['first-reservation','pause-policy'] and state['reserve']==1


def test_progression_excludes_active_unknown_and_preserves_started_descendants(case):
    from mideagent_orchestrator.start_queue_progress import advance_start_queue
    runtime,queue,db,state=case
    active=job(db,40,started=True);descendant=job(db,41,started=True)
    enroll(queue,db,active);enroll(queue,db,descendant)
    db.jobs[active['id']]['active']=True
    queue.patch(OWNER,2,paused=True)
    calls=[]
    assert advance_start_queue(runtime,OWNER,lambda owner,id:calls.append(id))
    assert calls==[descendant['id']]


def test_actual_priority_predicate_prepares_head_and_uses_other_available_slot(case):
    runtime,queue,db,state=case
    a,b=job(db,40),job(db,41)
    enroll(queue,db,a);enroll(queue,db,b)
    method=execution_methods()['_queue_start_ready_in']
    runtime._queue_start_ready_in=lambda conn,row:method(runtime,conn,row)
    runtime.capacity_unavailable.add(a['id'])
    assert runtime.claim_next(OWNER,a['id']) is None
    assert state['reserve']==0 and state['enroll']==1  # Native demand preparation only.
    assert runtime.claim_next(OWNER,b['id'])['run_id']==b['id']
    assert state['reserve']==1


def test_actual_controller_result_path_advances_new_queue_after_commit(case):
    runtime,queue,db,state=case
    first=job(db,40)
    enroll(queue,db,first)
    path=ROOT/'apps/orchestrator/mideagent_orchestrator/controller.py'
    cls=next(n for n in ast.parse(path.read_text(encoding='utf8')).body if isinstance(n,ast.ClassDef) and n.name=='BrokerController')
    nodes=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'dispatch','advance_queue'}]
    ns={'__name__':'mideagent_orchestrator.controller','__package__':'mideagent_orchestrator'}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
    calls=[]
    controller=SimpleNamespace(runtime=runtime,_dispatch_exact=lambda owner,id:calls.append(id) or {'id':id})
    controller.advance_queue=lambda owner:ns['advance_queue'](controller,owner)
    state=ns['dispatch'](controller,OWNER,'synthetic-just-completed')
    assert calls==['synthetic-just-completed',first['id']] and state['id']=='synthetic-just-completed'
    # Actual receive() still accepts/commits before calling this dispatch wrapper.
    receive=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='receive')
    effects=[n.func.attr for n in ast.walk(receive) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'accept','dispatch'}]
    assert effects==['accept','dispatch']


def test_new_reserved_pending_delivery_wakes_without_dispatcher_but_unknown_is_untouched(case):
    from mideagent_orchestrator.start_queue_progress import advance_start_queue
    runtime,queue,db,state=case
    pending=job(db,40,started=True);unknown=job(db,41,started=True)
    for value in (pending,unknown):enroll(queue,db,value)
    db.jobs[pending['id']].update(active=True,deliverable=True)
    db.jobs[unknown['id']].update(active=True,deliverable=True,uncertain=True)
    queue.patch(OWNER,2,paused=True)
    calls=[]
    assert advance_start_queue(runtime,OWNER,lambda owner,id:calls.append(id))
    assert calls==[pending['id']]


def test_local_fleet_busy_head_does_not_block_other_available_cpu_role(case, fleet_case, monkeypatch):
    runtime, queue, db, state = case
    fleet, fleet_db, alive_calls, live = fleet_case
    runtime.fleet = fleet
    runtime._engine_role = lambda node: None
    a, b = job(db, 40), job(db, 41)
    b['snapshot']['definition']['nodes'][0]['type'] = 'extract_audio'
    enroll(queue, db, a)
    enroll(queue, db, b)
    method = execution_methods()['_queue_start_ready_in']
    runtime._queue_start_ready_in = lambda conn, row: method(runtime, conn, row)
    execute = db.execute

    def with_fleet(sql, params=()):
        if 'FROM agent_configurations' in sql or 'FROM agent_instances' in sql or sql.startswith('UPDATE agent_instances'):
            return fleet_db.execute(sql, params)
        if sql.startswith('UPDATE node_runs SET agent_instance_id='):
            instance, owner, identity, run_id = params
            next(run for run in db.jobs[identity]['runs'] if run['id'] == run_id)['agent_instance_id'] = instance
            return SimpleNamespace(fetchone=lambda: None)
        return execute(sql, params)

    monkeypatch.setattr(db, 'execute', with_fleet)
    before = deepcopy((fleet_db.configs, fleet_db.instances, live))
    assert queue.allowed_in(db, b), 'Busy local Fleet head must not outrank an available other CPU role'
    assert before == (fleet_db.configs, fleet_db.instances, live)
    assert state == dict(capture=0, reserve=0, enroll=0)
    assert all(sql.startswith('SELECT ') and 'FOR ' not in sql for sql, _ in fleet_db.calls)

    reservations = []
    reserve = fleet.reserve
    def actual_reserve(conn, agent):
        reservations.append(agent)
        return reserve(conn, agent)
    monkeypatch.setattr(fleet, 'reserve', actual_reserve)
    fleet_db.read_only = False
    assert runtime.claim_next(OWNER, b['id'])['run_id'] == b['id']
    assert reservations == ['extract_audio'] and state['reserve'] == 1
    assert fleet_db.instances[0]['in_flight'] == 1
    assert fleet_db.instances[1]['in_flight'] == 1
    assert db.jobs[b['id']]['runs'][0]['agent_instance_id'] == 'free-b'


@pytest.mark.parametrize('branch,expected', [
    ('no-fleet', True), ('engine-role', True), ('non-cpu', True), ('agent-pool-unavailable', False),
])
def test_local_fleet_priority_probe_preserves_other_routing_branches(case, branch, expected):
    runtime, queue, db, state = case
    value = job(db, 40)
    def forbidden(*args):
        raise AssertionError('This routing branch must not probe or reserve local Fleet')
    runtime.fleet = SimpleNamespace(can_reserve=forbidden, reserve=forbidden, get=forbidden)
    runtime._engine_role = forbidden
    if branch == 'no-fleet':
        runtime.fleet = None
    elif branch == 'engine-role':
        value['snapshot']['definition']['nodes'][0].update(
            type='preprocess_audio', options={'vad_mode': 'nvidia'},
        )
        runtime._engine_role = lambda node: 'preprocess_audio'
    elif branch == 'non-cpu':
        value['snapshot']['definition']['nodes'][0]['type'] = 'select'
    else:
        runtime.capacity_unavailable.add(value['id'])
    method = execution_methods()['_queue_start_ready_in']
    assert method(runtime, db, value) is expected
    assert state == dict(capture=0, reserve=0, enroll=0)
