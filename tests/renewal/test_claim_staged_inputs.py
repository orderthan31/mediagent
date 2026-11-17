"""Ready-node byte/lock evidence: actual Execution, S3 adapter, disposable PG.

Synthetic media only. Model transports are fail-if-called; no delivery occurs.
"""
from collections import Counter
from uuid import uuid4

import pytest

from test_execution import admin, db, movie, admit
from test_claim_cold_gate import CountedS3, counts
from test_model_role_orchestration import formal
from video_service.object_store import S3ContentStore


class ByteCountedS3(CountedS3):
    def __init__(self):
        super().__init__()
        self.byte_reads = []
        self.before_content = None

    def get_object(self, **kwargs):
        key = kwargs['Key']
        if '/start-queues/' not in key:
            if self.before_content:
                self.before_content(key)
            if key in self.objects:
                self.byte_reads.append((key, len(self.objects[key]['raw'])))
        return super().get_object(**kwargs)


def audio_ready(db, admin, movie, tmp_path, monkeypatch, *, cap='auto'):
    import test_model_role_orchestration as fixture
    original = fixture.audio_graph

    def definition(*args):
        graph = original(*args)
        # formal sets numeric options; alter saved definition before freezing only.
        return graph

    client = ByteCountedS3()
    store = S3ContentStore(client, 'synthetic-staged', tmp_path, prefix='staged')
    from video_service.postgres.execution import Execution
    save = Execution.save_definition

    def save_definition(self, owner, identity, definition, *args, **kwargs):
        for node in definition['nodes']:
            if node['type'] in {'transcribe', 'translate'}:
                node['options']['max_model_calls'] = cap
        return save(self, owner, identity, definition, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Execution, 'save_definition', save_definition)
        runtime, owner, job = formal(db, admin, movie, tmp_path, store=store, prepare=False)
    admit(runtime, owner, job['id'])
    for expected in ('extract_audio', 'preprocess_audio'):
        command = runtime.claim_next(owner, job['id'])
        assert command['agent']['id'] == expected
        result = runtime.execute_command(owner, command)
        assert result['status'] == 'completed'
        runtime.accept(owner, command, result)
    client.calls.clear()
    client.byte_reads.clear()
    return runtime, owner, job, client


def test_exact_ready_audio_get_keys_and_bytes(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    with db.connection() as conn:
        current = runtime._job(conn, owner, job['id'])
        runs = runtime._runs(conn, owner, job['id'])
        node, inputs, skipped = next(runtime._claim_candidates(current, {r['node_id']: r for r in runs}))
    assert node['type'] == 'transcribe' and skipped is None
    expected = {runtime.store._key(ref.get('source_owner_id', owner), ref['storage_key']): ref['bytes'] for ref in inputs.values()}
    command = runtime.claim_next(owner, job['id'])
    assert command['inputs'] == inputs
    reads = Counter(key for key, _ in client.byte_reads)
    assert set(reads) == set(expected), 'ready-node staging must omit unrelated original/extracted history'
    assert sum(size for _, size in client.byte_reads) == sum(expected[key] * n for key, n in reads.items())
    assert all(size == expected[key] for key, size in client.byte_reads)
    assert command['transcription']['max_model_calls'] == 1
    # Three commands plus the two actual CPU result-accepted events.
    assert counts(db, job) == (3, 5, 0)


def test_all_content_reads_release_owner_job_and_role_locks(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    checked = []

    def inspect_locks(key):
        with db.connection() as conn:
            conn.execute("SET LOCAL lock_timeout='500ms'")
            conn.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
            for name in ('start-queue:' + owner, 'agent-pool-capacity:transcription'):
                assert conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked', (name,)).fetchone()['locked']
        checked.append(key)

    client.before_content = inspect_locks
    assert runtime.claim_next(owner, job['id'])['agent']['id'] == 'transcribe'
    assert checked
