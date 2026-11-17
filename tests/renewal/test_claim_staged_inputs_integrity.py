"""Selected closure integrity and exact off-lock budget semantics."""
from collections import Counter
from copy import deepcopy
import io
import json
import wave
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from test_claim_staged_inputs import admin, db, movie, audio_ready, ByteCountedS3
from test_claim_cold_gate import prepared, observe, counts
from test_execution import admit
from test_model_role_orchestration import formal
from video_service.object_store import S3ContentStore, ObjectIntegrityError
from video_service.canonical import canonical


@pytest.mark.parametrize('cap', ['auto', '3'])
def test_exact_budget_builder_once_off_lock_and_historical_numeric(db, admin, movie, tmp_path, monkeypatch, cap):
    import video_service.model_call_budget as budget
    from video_service.cpu_input_policy import lease_seconds
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch, cap=cap)
    original = budget.resolve
    calls = []

    def resolve(store, actor, command, **kwargs):
        with db.connection() as conn:
            conn.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
            assert conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked', ('start-queue:'+owner,)).fetchone()['locked']
        calls.append(deepcopy(command))
        return original(store, actor, command, **kwargs)

    monkeypatch.setattr(budget, 'resolve', resolve)
    command = runtime.claim_next(owner, job['id'])
    assert len(calls) == (1 if cap == 'auto' else 0)
    config = command['transcription']
    assert config['max_model_calls'] == (1 if cap == 'auto' else 3)
    assert budget.frozen_cap(command) == config['max_model_calls']
    assert lease_seconds(command) == config['max_runtime_seconds']
    before = len(client.byte_reads)
    # Enrollment/worker's independent verifier must still make ordinary reads.
    budget.verify(runtime.store, owner, command, policy_version=2)
    assert len(client.byte_reads) == before + (1 if cap == 'auto' else 0)


def test_transcript_successor_omits_all_audio_history_broad_approvals_still_read_it(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    command = runtime.claim_next(owner, job['id'])
    transcript = runtime.store.put(owner, [canonical([{'start':0.0,'end':0.2,'text':'synthetic transcript fixture'}])], 'transcript')
    # Synthetic accepted frontier only, not a model response or provider invocation.
    with db.connection() as conn:
        conn.execute("UPDATE node_runs SET status='completed',completed_at=now(),result=%s WHERE id=%s", (Jsonb({'outputs':{'transcript':transcript},'fixture':'synthetic frontier'}),command['attempt_id']))
    video = job['snapshot']['inputs']['video']
    oldkey = runtime.store._key(owner, video['storage_key'])
    raw = client.objects[oldkey]['raw']
    client.objects[oldkey]['raw'] = bytes([raw[0] ^ 1]) + raw[1:]
    client.calls.clear(); client.byte_reads.clear()
    successor = runtime.claim_next(owner, job['id'])
    assert successor['agent']['id'] == 'translate'
    key = runtime.store._key(owner, transcript['storage_key'])
    assert client.byte_reads == [(key, transcript['bytes'])] * 2
    assert successor['translation']['model_call_plan']['planned_units'] == 1
    assert successor['translation']['max_model_calls'] == 1
    for operation in (lambda:runtime.plan(owner,job['id']),
                      lambda:runtime.confirm(owner,job['id'],'irrelevant',uuid4().hex),
                      lambda:runtime.admit(owner,job['id'],uuid4().hex,uuid4().hex)):
        with pytest.raises(ObjectIntegrityError):
            operation()
    # Four commands plus the two actual CPU result-accepted events.
    assert counts(db,job) == (4,6,0)


@pytest.mark.parametrize('failure', ['remote_tamper', 'remote_missing', 'denied', 'local_corrupt', 'local_symlink'])
def test_selected_input_integrity_is_never_a_warm_cas_cache(db, admin, movie, tmp_path, monkeypatch, failure):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path)
    observe(db)
    ref = job['snapshot']['inputs']['video']
    key = runtime.store._key(owner, ref['storage_key'])
    path = runtime.store.path(owner, ref)
    if failure == 'remote_tamper':
        raw = client.objects[key]['raw']; client.objects[key]['raw'] = bytes([raw[0]^1])+raw[1:]
    elif failure == 'remote_missing':
        del client.objects[key]
    elif failure == 'denied':
        get = client.get_object
        def denied(**kwargs):
            if kwargs['Key'] == key:
                raise PermissionError('synthetic denied')
            return get(**kwargs)
        monkeypatch.setattr(client,'get_object',denied)
    elif failure == 'local_corrupt':
        path.chmod(0o600)
        path.write_bytes(b'x' * ref['bytes'])
    else:
        path.unlink()
        target = tmp_path/'synthetic-outside'
        target.write_bytes(b'x' * ref['bytes'])
        path.symlink_to(target)
    with pytest.raises((ValueError, OSError, KeyError)):
        runtime.claim_next(owner,job['id'])
    assert counts(db,job) == (0,0,0)
    if failure == 'local_corrupt':
        assert path.read_bytes() == b'x'*ref['bytes'], 'never heal corrupt local CAS'


def test_each_logical_audio_read_rechecks_mid_operation_remote_change(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    with db.connection() as conn:
        rows = runtime._runs(conn,owner,job['id'])
    ref = rows[-1]['result']['outputs']['audio']
    key = runtime.store._key(owner,ref['storage_key'])
    original = client.get_object
    count = []
    def changing(**kwargs):
        if kwargs['Key'] == key:
            count.append(key)
            if len(count) == 2:
                raw=client.objects[key]['raw']; client.objects[key]['raw']=bytes([raw[0]^1])+raw[1:]
        return original(**kwargs)
    monkeypatch.setattr(client,'get_object',changing)
    before=counts(db,job)
    with pytest.raises(ObjectIntegrityError):
        runtime.claim_next(owner,job['id'])
    assert len(count)==2 and counts(db,job)==before


@pytest.mark.parametrize('channels,width,rate', [(2,2,16000),(1,1,16000),(1,2,8000)])
def test_selected_normalized_audio_contract_rejects_wrong_pcm(db, admin, movie, tmp_path, monkeypatch, channels, width, rate):
    runtime, owner, job, client = audio_ready(db, admin, movie, tmp_path, monkeypatch)
    raw=io.BytesIO()
    with wave.open(raw,'wb') as wav:
        wav.setnchannels(channels);wav.setsampwidth(width);wav.setframerate(rate)
        wav.writeframes(b'\x00' * channels*width*100)
    ref=runtime.store.put(owner,[raw.getvalue()],'audio')
    with db.connection() as conn:
        row=runtime._runs(conn,owner,job['id'])[-1]
        result=deepcopy(row['result']);result['outputs']['audio']=ref
        conn.execute('UPDATE node_runs SET result=%s WHERE id=%s',(Jsonb(result),row['id']))
    before=counts(db,job)
    with pytest.raises(ValueError,match='bounded_pcm'):
        runtime.claim_next(owner,job['id'])
    assert counts(db,job)==before


def test_selected_original_stereo_audio_uses_frozen_origin_not_pcm_contract(db, admin, movie, tmp_path, monkeypatch):
    from test_audio_original_input import pcm
    from mideagent_orchestrator.workflow import default_definition, selected_definition
    client=ByteCountedS3()
    runtime,owner,legacy=formal(db,admin,movie,tmp_path,store=S3ContentStore(client,'synthetic-audio',tmp_path,prefix='audio'),prepare=False)
    source=default_definition()
    source['nodes'][0]['model_ref']=next(n['model_ref'] for n in legacy['snapshot']['definition']['nodes'] if n['type']=='transcribe')
    chosen=selected_definition(source,{'audio_goal':{'node_id':'transcription','options':{'source_language':'en'}}})
    saved=runtime.save_definition(owner,uuid4().hex,chosen)
    asset=runtime.ingest(owner,'stereo.wav',pcm())
    job=runtime.create(owner,asset['asset_id'],saved['id'],saved['revision'],request_id=uuid4().hex,options={'source_language':'en','target_language':'ko'})
    admit(runtime,owner,job['id'])
    client.calls.clear();client.byte_reads.clear()
    command=runtime.claim_next(owner,job['id'])
    assert command['agent']['id']=='preprocess_audio'
    assert job['snapshot']['audio_origin_policy']['media']['channels']==2
    ref=job['snapshot']['inputs']['audio']
    assert client.byte_reads==[(runtime.store._key(owner,ref['storage_key']),ref['bytes'])]
    assert counts(db,job)==(1,1,0)
