"""Actual admitted model frontier, no model/provider transport or GPU execution."""
import pytest

from test_claim_cold_gate import admin, db, movie, CountedS3, observe, demands
from test_agent_control_pool_admission import model_counts
from video_service.object_store import S3ContentStore


def prepared_model(db, admin, movie, tmp_path, monkeypatch):
    import test_agent_control_pool_admission as existing
    from test_model_role_orchestration import formal
    client = CountedS3()
    cache = tmp_path / 's3-cache'
    cache.mkdir()
    store = S3ContentStore(client, 'synthetic-model-bucket', cache, prefix='cold-model')
    # Reuse the real admitted fixture, replacing only its byte-level store adapter.
    def remote_formal(*args, **kwargs):
        return formal(*args, **kwargs, store=store)
    with monkeypatch.context() as scoped:
        scoped.setattr(existing, 'formal', remote_formal)
        runtime, owner, job, coordinator, published = existing.prepared(db, admin, movie, tmp_path)
    client.calls.clear()
    return runtime, owner, job, client, coordinator, published


def ledger_counts(db, job):
    with db.connection() as conn:
        return tuple(conn.execute(sql, (job['id'],)).fetchone()['n'] for sql in (
            'SELECT count(*) n FROM model_call_budgets WHERE job_id=%s',
            'SELECT count(*) n FROM model_chunk_attempts WHERE job_id=%s',
            'SELECT count(*) n FROM model_role_tool_calls c JOIN model_role_tasks t USING(task_id) WHERE t.job_id=%s',
        ))


def test_model_cold_corruption_is_deferred_then_full_preflight_rejects(db, admin, movie, tmp_path, monkeypatch):
    from video_service.object_store import ObjectIntegrityError
    runtime, owner, job, client, _, published = prepared_model(db, admin, movie, tmp_path, monkeypatch)
    key = runtime.store._key(owner, job['snapshot']['inputs']['video']['storage_key'])
    raw = client.objects[key]['raw']
    client.objects[key]['raw'] = bytes([raw[0] ^ 1]) + raw[1:]
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads and not published
    observe(db, role='transcription')
    with pytest.raises(ObjectIntegrityError):
        runtime.claim_next(owner, job['id'])
    assert client.content_reads and model_counts(db, job) == (0, 0, 0)
    assert ledger_counts(db, job) == (0, 0, 0) and not published


@pytest.mark.parametrize('cold_first', [False, True])
def test_model_cold_preparation_no_media_no_budget_then_one_ready_command(db, admin, movie, tmp_path, monkeypatch, cold_first):
    runtime, owner, job, client, coordinator, published = prepared_model(db, admin, movie, tmp_path, monkeypatch)
    assert job['snapshot'].get('audio_pipeline_policy')
    before = ledger_counts(db, job)
    assert before == (0, 0, 0)
    if cold_first:
        for _ in range(2):
            assert runtime.claim_next(owner, job['id']) is None
        assert not client.content_reads
        assert len(demands(db, job)) == 1 and demands(db, job)[0]['node_run_id'] is None
    assert model_counts(db, job) == (0, 0, 0) and ledger_counts(db, job) == before
    assert not published
    observe(db, role='transcription')
    command = runtime.claim_next(owner, job['id'])
    assert command['agent']['id'] == 'transcribe' and client.content_reads
    from video_service.long_audio_budget import command_budget
    from video_service.model_call_budget import resolve
    from video_service.role_policy import snapshot_version
    resolved = resolve(runtime.store, owner, command, policy_version=snapshot_version(job['snapshot']))
    assert command['transcription']['max_model_calls'] == resolved['max_model_calls']
    assert command['resource_budget'] == command_budget('transcribe', command['options'], resolved_cap=resolved['max_model_calls'])
    assert model_counts(db, job) == (1, 0, 1)
    assert ledger_counts(db, job) == before and not published
    # This fixture's publish transport only appends to a local list. No broker.
    assert coordinator.publish(owner, command)
    assert model_counts(db, job) == (1, 1, 1) and len(published) == 1
    assert ledger_counts(db, job) == before
    assert runtime.claim_next(owner, job['id']) is None
    assert model_counts(db, job) == (1, 1, 1) and len(published) == 1
