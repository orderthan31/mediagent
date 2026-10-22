"""Real disposable PG; injected publisher only, not a live broker/media E2E."""
from uuid import uuid4
import pytest
from test_foundation import db as _db, admin as _admin
from test_execution import movie as _movie, setup, admit, graph
from video_service.content_store import ContentStore
from video_service.postgres.execution import Execution
from video_service.postgres.remote_control import RemoteControl
from video_service.postgres.dispatch_queue import DispatchQueue
from video_service.rabbitmq_controller import BrokerController

db, admin, movie = _db, _admin, _movie


class UnitObjectStore(ContentStore):
    """Local verified bytes behind the object-store interface in this unit seam."""
    storage_kind = 's3'


class Publisher:
    def __init__(self):
        self.sent = []
    def __call__(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def publish(self, delivery):
        self.sent.append(delivery)
        return True


def prepared(db, admin, movie, tmp_path, definition=None):
    runtime = Execution(db, UnitObjectStore(tmp_path))
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie, definition or graph('encode'))
    admit(runtime, owner, job['id'])
    control = RemoteControl(db)
    worker, boot = uuid4().hex, uuid4().hex
    control.provision('encode', 'a' * 64, [worker])
    control.publish('encode', 'a' * 64, [{'id': worker, 'boot_id': boot,
        'running': False, 'state': 'stopped', 'started_at': '2026-01-01T00:00:00Z'}])
    publisher = Publisher()
    controller = BrokerController(runtime, publisher)
    return runtime, owner, job, control, worker, boot, publisher, controller


def enable(db, control, worker, boot):
    with db.connection() as c:
        c.execute("UPDATE remote_control_groups SET enabled=true,replicas=1 WHERE agent_id='encode'")
    control.publish('encode', 'a' * 64, [{'id': worker, 'boot_id': boot,
        'running': True, 'state': 'ready', 'started_at': '2026-01-01T00:00:00Z'}])


def test_stopped_worker_holds_job_without_delivery_or_lease(db, admin, movie, tmp_path):
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    state = ctl.dispatch(owner, job['id'])
    assert state['status'] == 'waiting'
    assert len(state['runs']) == 1
    run = state['runs'][0]
    assert run['status'] == 'waiting'
    assert run['started_at'] is None and run['lease_expires_at'] is None
    assert run['dispatch']['phase'] == 'pending'
    assert pub.sent == []
    with db.connection() as c:
        c.execute("UPDATE broker_dispatch_queue SET created_at=now()-interval '90 seconds'")
    assert ctl.dispatch(owner, job['id'])['runs'][0]['id'] == run['id']
    assert pub.sent == []
    enable(db, control, worker, boot)
    DispatchQueue(rt).tick(ctl, agent='encode')
    state = rt.get(owner, job['id'])
    assert state['status'] == 'waiting'  # Published is not actual processing.
    assert state['runs'][0]['dispatch']['phase'] == 'sent'
    assert state['runs'][0]['started_at'] is None
    assert state['runs'][0]['lease_expires_at'] is not None
    assert len(pub.sent) == 1
    DispatchQueue(rt).tick(ctl, agent='encode')
    assert len(pub.sent) == 1


def test_actual_matching_worker_receipt_starts_processing(db, admin, movie, tmp_path):
    from video_service.postgres.worker_telemetry import WorkerTelemetry
    from video_service.worker_telemetry import exchange
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    enable(db, control, worker, boot)
    state = ctl.dispatch(owner, job['id'])
    attempt = state['runs'][0]['id']
    assert state['status'] == 'waiting'
    report = {'version': 1, 'worker_id': worker, 'boot_id': '0' * 32, 'family': 'cpu',
              'role': 'encode', 'state': 'busy', 'sequence': 0,
              'ticket_id': job['id'], 'attempt_id': attempt}
    telemetry = WorkerTelemetry(db)
    telemetry.accept(report, exchange('cpu', 'encode'), expected_worker_id=worker)
    DispatchQueue(rt).tick(ctl, agent='encode')
    assert rt.get(owner, job['id'])['runs'][0]['status'] == 'waiting'
    telemetry.accept({**report, 'boot_id': boot, 'sequence': 1},
                     exchange('cpu', 'encode'), expected_worker_id=worker)
    DispatchQueue(rt).tick(ctl, agent='encode')
    state = rt.get(owner, job['id'])
    assert state['status'] == 'running'
    assert state['runs'][0]['dispatch']['phase'] == 'received'
    assert state['runs'][0]['started_at'] is not None
    assert len(pub.sent) == 1


def test_cancel_waiting_never_publishes_and_late_result_is_quarantined(db, admin, movie, tmp_path):
    from video_service.cpu_agents import digest
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    state = ctl.dispatch(owner, job['id'])
    command = state['runs'][0]['request']
    state = rt.cancel(owner, job['id'], state['revision'])
    assert state['status'] == 'cancelled'
    enable(db, control, worker, boot)
    DispatchQueue(rt).tick(ctl, agent='encode')
    assert pub.sent == []
    result = {k: command[k] for k in ('protocol_version', 'run_id', 'attempt_id', 'generation', 'agent')}
    result.update(status='completed', outputs={}, transport='s3_subprocess', request_sha256=digest(command))
    assert rt.accept(owner, command, result)['status'] == 'cancelled'
    with db.connection() as c:
        assert c.execute('SELECT count(*) n FROM result_quarantine').fetchone()['n'] == 1
        assert c.execute('SELECT published_at FROM message_outbox WHERE id=%s', (command['attempt_id'],)).fetchone()['published_at'] is None


def test_concurrent_dispatch_is_one_attempt_and_one_publish(db, admin, movie, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    enable(db, control, worker, boot)
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda _: ctl.dispatch(owner, job['id']), range(4)))
    assert len(pub.sent) == 1
    assert len({s['runs'][0]['id'] for s in states}) == 1
    with db.connection() as c:
        assert c.execute('SELECT count(*) n FROM broker_dispatch_queue').fetchone()['n'] == 1


def test_ambiguous_send_blocks_automatic_republication(db, admin, movie, tmp_path):
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    enable(db, control, worker, boot)
    calls = []
    def unknown(delivery):
        calls.append(delivery)
        raise OSError('simulated lost confirmation in unit seam')
    pub.publish = unknown
    state = ctl.dispatch(owner, job['id'])
    assert state['runs'][0]['dispatch']['phase'] == 'unknown'
    DispatchQueue(rt).tick(ctl, agent='encode')
    ctl.dispatch(owner, job['id'])
    assert len(calls) == 1


def test_preexisting_attempt_is_not_enrolled_or_republished(db, admin, movie, tmp_path):
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path)
    rt.defer_broker_agents = frozenset()
    command = rt.claim_next(owner, job['id'])
    with db.connection() as c:
        c.execute('UPDATE message_outbox SET published_at=now() WHERE id=%s', (command['attempt_id'],))
    before = rt.get(owner, job['id'])
    rt.defer_broker_agents = frozenset({'encode'})
    DispatchQueue(rt).tick(ctl, agent='encode')
    assert rt.get(owner, job['id']) == before
    assert pub.sent == []
    with db.connection() as c:
        assert c.execute('SELECT count(*) n FROM broker_dispatch_queue').fetchone()['n'] == 0


def test_waiting_branch_does_not_hide_an_already_running_branch(db, admin, movie, tmp_path):
    definition = graph('validate_video')
    definition['nodes'].append({'id': 'second', 'type': 'encode', 'position': {'x': 300, 'y': 50}, 'options': {'subtitle_mode': 'none'}})
    definition['edges'].append({'id': 'parallel', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'second', 'port': 'video'}})
    rt, owner, job, control, worker, boot, pub, ctl = prepared(db, admin, movie, tmp_path, definition)
    ctl.dispatch(owner, job['id'])
    state = ctl.dispatch(owner, job['id'])
    assert sorted(r['status'] for r in state['runs']) == ['running', 'waiting']
    assert state['status'] == 'running'
