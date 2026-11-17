"""Actual Execution + counted S3 protocol + explicitly disposable PostgreSQL.

No provider/model/worker transport is invoked. Queue authority GETs are not media.
"""
from uuid import uuid4

import pytest

from test_execution import admin, db, movie, setup, graph, admit
from test_start_queue_storage import ConditionalS3
from video_service.object_store import S3ContentStore, ObjectIntegrityError
from video_service.postgres.execution import Execution


class CountedS3(ConditionalS3):
    @property
    def content_reads(self):
        return [key for verb, key in self.calls if verb == 'GET' and '/start-queues/' not in key]


def prepared(db, admin, movie, tmp_path, definition=None):
    client = CountedS3()
    runtime = Execution(db, S3ContentStore(client, 'synthetic-bucket', tmp_path, prefix='cold-gate'))
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie, definition or graph('encode', 'validate_video'))
    admit(runtime, owner, job['id'])
    with db.connection() as conn:
        conn.execute("INSERT INTO agent_pool_roles(role,max_instances,memory_bytes,idle_seconds,template_sha256,enabled) VALUES ('encode',1,512,30,%s,true)", ('a' * 64,))
    client.calls.clear()
    return runtime, owner, job, client


def observe(db, observation='ready', role='encode'):
    with db.connection() as conn:
        if observation == 'absent':
            return
        if observation == 'other_role':
            role = 'analyze'
            conn.execute("INSERT INTO agent_pool_roles SELECT 'analyze',max_instances,memory_bytes,idle_seconds,template_sha256,enabled FROM agent_pool_roles WHERE role='encode'")
        conn.execute("INSERT INTO agent_pool_instances(id,role,slot,template_sha256,phase,observed_at) VALUES (%s,%s,0,%s,%s,now() - %s * interval '1 second') ON CONFLICT (role,slot) WHERE phase<>'removed' DO UPDATE SET phase=EXCLUDED.phase,observed_at=EXCLUDED.observed_at", (uuid4().hex, role, 'a' * 64, observation if observation in {'starting', 'busy'} else 'ready', 10 if observation == 'stale' else 0))


def counts(db, job):
    with db.connection() as conn:
        return tuple(conn.execute(sql, (job['id'],)).fetchone()['n'] for sql in (
            'SELECT count(*) n FROM node_runs WHERE job_id=%s',
            'SELECT count(*) n FROM message_outbox WHERE aggregate_id=%s',
            'SELECT count(*) n FROM model_role_tasks WHERE job_id=%s',
        ))


def demands(db, job):
    with db.connection() as conn:
        return conn.execute('SELECT * FROM agent_pool_demands WHERE job_id=%s', (job['id'],)).fetchall()


@pytest.mark.parametrize('observation', ['absent', 'starting', 'busy', 'stale', 'other_role'])
def test_cold_claim_has_no_content_reads(db, admin, movie, tmp_path, observation):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db, observation)
    for _ in range(2):
        assert runtime.claim_next(owner, job['id']) is None
    assert client.content_reads == [], 'authorized cold demand must precede media preflight'
    assert any('/start-queues/' in key for verb, key in client.calls if verb == 'GET')
    pending = demands(db, job)
    assert len(pending) == 1 and pending[0]['node_run_id'] is None
    assert counts(db, job) == (0, 0, 0)


def test_cold_then_ready_rechecks_remote_bytes(db, admin, movie, tmp_path):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads
    observe(db)
    command = runtime.claim_next(owner, job['id'])
    assert command['agent']['id'] == 'encode'
    assert client.content_reads
    assert counts(db, job) == (1, 1, 0)
    assert demands(db, job)[0]['node_run_id'] == command['attempt_id']


def test_cold_defers_corruption_but_ready_rejects(db, admin, movie, tmp_path):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    key = runtime.store._key(owner, job['snapshot']['inputs']['video']['storage_key'])
    raw = client.objects[key]['raw']
    client.objects[key]['raw'] = bytes([raw[0] ^ 1]) + raw[1:]
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads
    observe(db)
    with pytest.raises(ObjectIntegrityError):
        runtime.claim_next(owner, job['id'])
    assert client.content_reads and counts(db, job) == (0, 0, 0)
