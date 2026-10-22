"""Real disposable PostgreSQL + RabbitMQ; no worker/media/operating faults."""
import os
from uuid import uuid4

import pika
import pytest
from test_dispatch_queue import db, admin, movie, prepared, enable
from video_service.durable_transport import DurableTransport


@pytest.fixture(autouse=True)
def sender_identity(db):
    from psycopg.conninfo import make_conninfo
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    db.fence_application = 'isolated-send-fence-' + uuid4().hex
    db.dsn = make_conninfo(db.dsn, application_name=db.fence_application)


@pytest.fixture
def broker():
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host=os.environ['FENCE_BROKER_HOST'],
        credentials=pika.PlainCredentials('fixture', os.environ['FENCE_BROKER_PASSWORD']),
        socket_timeout=5, blocked_connection_timeout=5))
    channel = connection.channel()
    queue = 'isolated-send-fence-' + uuid4().hex
    channel.queue_declare(queue=queue, durable=True)
    channel.confirm_delivery()
    yield channel, queue
    # Keep messages for inspection; the owning disposable container is removed.
    connection.close()


def publish(broker, identity, body):
    channel, queue = broker
    channel.basic_publish(exchange='', routing_key=queue, body=body,
                          mandatory=True, properties=pika.BasicProperties(
                              message_id=identity, delivery_mode=2))
    return True


def count(broker):
    channel, queue = broker
    return channel.queue_declare(queue=queue, passive=True).method.message_count


def waiting(db, admin, movie, tmp_path):
    values = prepared(db, admin, movie, tmp_path)
    rt, owner, job, control, worker, boot, publisher, controller = values
    state = controller.dispatch(owner, job['id'])
    enable(db, control, worker, boot)
    return values, state['runs'][0]['id']


def test_send_intent_is_committed_before_real_broker_publication(db, admin, movie, tmp_path, broker):
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    observed = []
    def send(identity, kind, body):
        with db.connection() as independent:
            q = independent.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (identity,)).fetchone()
            observed.append(q['phase'])
        return publish(broker, identity, body)
    assert DurableTransport(rt).publish_exact(owner, job['id'], attempt, send)
    assert count(broker) == 1
    assert observed == ['sending']


def restart_and_retry(runtime, owner, job_id, attempt, broker):
    from types import SimpleNamespace
    from video_service.postgres.execution import Execution
    from video_service.postgres.dispatch_queue import DispatchQueue
    restarted = Execution(runtime.database, runtime.store)
    def exact(o, j, a):
        return DurableTransport(restarted).publish_exact(o, j, a, lambda identity, kind, body: publish(broker, identity, body))
    DispatchQueue(restarted).tick(SimpleNamespace(publish_exact=exact), agent='encode')
    exact(owner, job_id, attempt)
    with restarted.database.connection() as c:
        return dict(c.execute('SELECT phase,error_code FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone())


def test_db_connection_loss_after_real_delivery_cannot_republish(db, admin, movie, tmp_path, broker):
    import json
    import psycopg
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    def send(identity, kind, body):
        publish(broker, identity, body)
        # Terminate only the advisory-lock owner in this disposable database.
        with db.connection() as independent:
            pids = independent.execute("SELECT DISTINCT l.pid FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE l.locktype='advisory' AND l.granted AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND l.pid<>pg_backend_pid() AND a.application_name=%s", (db.fence_application,)).fetchall()
            assert len(pids) == 1
            assert independent.execute('SELECT pg_terminate_backend(%s) AS stopped', (pids[0]['pid'],)).fetchone()['stopped']
        return True
    with pytest.raises(psycopg.Error):
        DurableTransport(rt).publish_exact(owner, job['id'], attempt, send)
    with db.connection() as c:
        persisted = c.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase']
    restarted = restart_and_retry(rt, owner, job['id'], attempt, broker)
    messages = count(broker)
    print(json.dumps({'case': 'confirmed_delivery_then_DB_connection_loss', 'persisted_before_restart': persisted, 'after_restart': restarted['phase'], 'real_broker_messages_after_retry': messages}))
    assert persisted == 'sending'
    assert restarted['phase'] == 'unknown'
    assert messages == 1


CHILD = r'''
import json, os, sys, time
from pathlib import Path
import pika
from video_service.postgres import Database
from video_service.postgres.execution import Execution
from video_service.content_store import ContentStore
from video_service.durable_transport import DurableTransport
class UnitStore(ContentStore):
    storage_kind = 's3'
owner, job, attempt, queue, root, mode, marker, release = sys.argv[1:]
runtime = Execution(Database(os.environ['MIDEAGENT_TEST_DSN']), UnitStore(root))
def send(identity, kind, body):
    c = pika.BlockingConnection(pika.ConnectionParameters(host=os.environ['FENCE_BROKER_HOST'],
        credentials=pika.PlainCredentials('fixture',os.environ['FENCE_BROKER_PASSWORD']),
        socket_timeout=5,blocked_connection_timeout=5))
    ch=c.channel();ch.confirm_delivery()
    ch.basic_publish(exchange='',routing_key=queue,body=body,mandatory=True,
        properties=pika.BasicProperties(message_id=identity,delivery_mode=2))
    Path(marker).write_text('broker-confirmed')
    if mode == 'crash':
        os._exit(23)
    if mode == 'restart':
        c.close()
        return True
    deadline=time.monotonic()+15
    while not Path(release).exists():
        if time.monotonic()>deadline:raise TimeoutError('fixture release missing')
        time.sleep(.01)
    c.close()
    return True
if mode == 'restart':
    from types import SimpleNamespace
    from video_service.postgres.dispatch_queue import DispatchQueue
    def exact(o,j,a):return DurableTransport(runtime).publish_exact(o,j,a,send)
    DispatchQueue(runtime).tick(SimpleNamespace(publish_exact=exact),agent='encode')
    exact(owner,job,attempt)
    with runtime.database.connection() as db:
        q=db.execute('SELECT phase,error_code FROM broker_dispatch_queue WHERE node_run_id=%s',(attempt,)).fetchone()
    print(json.dumps(dict(q)))
else:
    DurableTransport(runtime).publish_exact(owner,job,attempt,send)
'''


def child_args(owner, job, attempt, broker, tmp_path, mode):
    import sys
    return [sys.executable, '-c', CHILD, owner, job['id'], attempt, broker[1],
            str(tmp_path), mode, str(tmp_path/'confirmed'), str(tmp_path/'release')]


def test_process_dies_inside_real_send_then_restart_cannot_republish(db, admin, movie, tmp_path, broker):
    import subprocess, json
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    child = subprocess.run(child_args(owner, job, attempt, broker, tmp_path, 'crash'), env=dict(os.environ, MIDEAGENT_TEST_DSN=rt.database.dsn), capture_output=True, text=True, timeout=20)
    assert child.returncode == 23, child.stderr
    assert (tmp_path/'confirmed').read_text() == 'broker-confirmed'
    assert count(broker) == 1
    with db.connection() as c:
        persisted = c.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase']
    restarted_child = subprocess.run(child_args(owner, job, attempt, broker, tmp_path, 'restart'), env=dict(os.environ, MIDEAGENT_TEST_DSN=rt.database.dsn), capture_output=True, text=True, timeout=20)
    assert restarted_child.returncode == 0, restarted_child.stderr
    restarted = json.loads(restarted_child.stdout)
    messages = count(broker)
    print(json.dumps({'case': 'process_exit_23_inside_real_send', 'exit_code': child.returncode, 'fresh_process_restart_exit': restarted_child.returncode, 'persisted_before_restart': persisted, 'after_restart': restarted['phase'], 'real_broker_messages_after_retry': messages}))
    assert persisted == 'sending'
    assert restarted['phase'] == 'unknown'
    assert messages == 1


def test_live_sender_is_not_mistaken_for_an_orphan(db, admin, movie, tmp_path, broker):
    import subprocess, time
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    child = subprocess.Popen(child_args(owner, job, attempt, broker, tmp_path, 'wait'), env=dict(os.environ, MIDEAGENT_TEST_DSN=rt.database.dsn), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline=time.monotonic()+10
        while not (tmp_path/'confirmed').exists() and child.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        assert (tmp_path/'confirmed').exists()
        observed = restart_and_retry(rt, owner, job['id'], attempt, broker)
        assert observed['phase'] == 'sending'
        assert count(broker) == 1
    finally:
        (tmp_path/'release').write_text('continue')
        _, error = child.communicate(timeout=15)
    assert child.returncode == 0, error
    with db.connection() as c:
        assert c.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase'] == 'sent'
    assert count(broker) == 1


def install_commit_fault(db, phase):
    assert phase in ('sending', 'sent')
    with db.connection() as c:
        c.execute("""CREATE FUNCTION isolated_fence_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.phase = TG_ARGV[0] THEN RAISE EXCEPTION 'isolated commit failure'; END IF; RETURN NEW; END $$""")
        ddl = ("CREATE CONSTRAINT TRIGGER isolated_commit_fault AFTER UPDATE ON broker_dispatch_queue DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION isolated_fence_commit_fault('sending')"
               if phase == 'sending' else
               "CREATE CONSTRAINT TRIGGER isolated_commit_fault AFTER UPDATE ON broker_dispatch_queue DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION isolated_fence_commit_fault('sent')")
        c.execute(ddl)


def test_failed_intent_commit_never_enters_external_sender(db, admin, movie, tmp_path, broker):
    import psycopg, json
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    install_commit_fault(db, 'sending')
    with pytest.raises(psycopg.Error):
        DurableTransport(rt).publish_exact(owner, job['id'], attempt,
            lambda identity, kind, body: publish(broker, identity, body))
    messages = count(broker)
    with db.connection() as c:
        phase = c.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase']
        lease = c.execute('SELECT lease_expires_at FROM node_runs WHERE id=%s', (attempt,)).fetchone()['lease_expires_at']
    print(json.dumps({'case': 'intent_commit_failed_before_IO', 'persisted_phase': phase, 'real_broker_messages': messages}))
    assert messages == 0
    assert phase == 'pending' and lease is None


def test_completion_commit_failure_keeps_durable_intent_and_no_republish(db, admin, movie, tmp_path, broker):
    import psycopg, json
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, *_ = values
    install_commit_fault(db, 'sent')
    with pytest.raises(psycopg.Error):
        DurableTransport(rt).publish_exact(owner, job['id'], attempt,
            lambda identity, kind, body: publish(broker, identity, body))
    assert count(broker) == 1
    with db.connection() as c:
        persisted = c.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase']
        c.execute('DROP TRIGGER isolated_commit_fault ON broker_dispatch_queue')
    restarted = restart_and_retry(rt, owner, job['id'], attempt, broker)
    messages = count(broker)
    print(json.dumps({'case': 'real_delivery_then_final_commit_failure', 'persisted_before_restart': persisted, 'after_restart': restarted['phase'], 'real_broker_messages_after_retry': messages}))
    assert persisted == 'sending'
    assert restarted['phase'] == 'unknown'
    assert messages == 1


@pytest.mark.parametrize('change', ['stop', 'cancel', 'boot'])
def test_admission_is_rechecked_after_the_durable_commit(db, admin, movie, tmp_path, broker, change):
    from contextlib import contextmanager
    from video_service.postgres.execution import Execution
    values, attempt = waiting(db, admin, movie, tmp_path)
    rt, owner, job, control, worker, boot, *_ = values
    observed = []
    def after_commit():
        with db.connection() as independent:
            observed.append(independent.execute('SELECT phase FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone()['phase'])
            if change == 'stop':
                independent.execute("UPDATE remote_control_groups SET enabled=false,replicas=0 WHERE agent_id='encode'")
        if change == 'cancel':
            current = rt.get(owner, job['id'])
            rt.cancel(owner, job['id'], current['revision'])
        if change == 'boot':
            control.publish('encode', 'a' * 64, [{'id': worker, 'boot_id': uuid4().hex,
                'running': True, 'state': 'ready', 'started_at': '2026-01-01T00:00:00Z'}])
    class BoundaryDatabase:
        @contextmanager
        def connection(self):
            with db.connection() as connection:
                class CommitBoundary:
                    def __getattr__(self, name):
                        return getattr(connection, name)
                    def commit(self):
                        connection.commit()
                        after_commit()
                yield CommitBoundary()
    isolated_runtime = Execution(BoundaryDatabase(), rt.store)
    sent = DurableTransport(isolated_runtime).publish_exact(owner, job['id'], attempt,
        lambda identity, kind, body: publish(broker, identity, body))
    assert sent is False
    assert observed == ['sending']
    assert count(broker) == 0
    with db.connection() as c:
        q = dict(c.execute('SELECT phase,error_code,boot_id,published_at FROM broker_dispatch_queue WHERE node_run_id=%s', (attempt,)).fetchone())
    assert q['phase'] == 'unknown' and q['error_code'] == 'dispatch_admission_changed'
    assert q['boot_id'] == boot and q['published_at'] is None
