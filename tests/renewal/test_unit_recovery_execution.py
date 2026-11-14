"""Same-job recovery through real CPU admission, role graphs, bridges and PG.

Only provider adapters are fakes. No preflight, adoption, DB, or scheduler stub is
used. The imported db fixture requires an explicit disposable DSN and owns its
random schema. ASR has three real 60-second logical chunks; MT has three real
100-row batches. The MT graph stops on its failed middle batch, leaving an
explicitly unresolved suffix. ASR's fanout legitimately completes its last chunk.
"""
import base64
from copy import deepcopy
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from test_execution import admin, admit, db, movie
from test_model_role_orchestration import formal
from app.unit_recovery_routes import mount_unit_recovery_routes
from mideagent_agents.transcription.model_graph import TranscriptionAgent
from mideagent_agents.translation.model_graph import TranslationAgent
from mideagent_model_runtime.broker import RoleReceiver
from mideagent_model_tools.client import RoleToolBridge
from mideagent_model_tools.endpoints import EndpointFailure
from mideagent_model_tools.unit_recovery import UnitRecoveryToolBridge
from mideagent_orchestrator.model_roles import ModelRoleCoordinator
from video_service.canonical import canonical, digest
from video_service.postgres import Conflict
from video_service.postgres.unit_recovery import RoleUnitRecovery
from video_service.role_policy import tool_context


def _long_movie(tmp_path):
    """Tiny synthetic video, but real 121-second PCM input after CPU preparation."""
    path = tmp_path / 'unit-recovery-121s.mp4'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
        'color=c=blue:s=32x32:r=1:d=121', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=16000:duration=121', '-threads', '1',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
        '-shortest', str(path),
    ], check=True, capture_output=True, timeout=60)
    return path.read_bytes()


def test_synthetic_long_fixture_really_has_three_logical_asr_chunks(tmp_path):
    """Offline executable fixture proof; not a substitute for the PG cases."""
    from video_service.audio_batches import split_normalized_audio
    _long_movie(tmp_path)
    wav = tmp_path / 'unit-recovery-normalized.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i',
                    str(tmp_path / 'unit-recovery-121s.mp4'), '-vn', '-ac', '1',
                    '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)],
                   check=True, capture_output=True, timeout=60)
    chunks = list(split_normalized_audio(wav.read_bytes(), chunk_frames=960000))
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.start for chunk in chunks] == [0, 60, 120]
    assert 121 <= chunks[-1].end < 122
    assert all(chunk.audio and len(chunk.sha256) == 64 for chunk in chunks)


def _history(case):
    """Full immutable root rows, not a selected subset masking counter changes."""
    with case.runtime.database.connection() as c:
        root = c.execute('SELECT * FROM model_role_tasks WHERE task_id=%s', (case.run,)).fetchone()
        calls = c.execute('SELECT * FROM model_role_tool_calls WHERE task_id=%s ORDER BY chunk_index', (case.run,)).fetchall()
        job = c.execute('SELECT snapshot,snapshot_sha256 FROM jobs WHERE id=%s', (case.job,)).fetchone()
        earlier = c.execute('SELECT * FROM node_runs WHERE job_id=%s AND id<>%s ORDER BY id', (case.job, case.run)).fetchall()
    return root, calls, job, earlier


def _effects(case):
    with case.runtime.database.connection() as c:
        return {
            'run': c.execute('SELECT * FROM node_runs WHERE id=%s', (case.run,)).fetchone(),
            'job': c.execute('SELECT * FROM jobs WHERE id=%s', (case.job,)).fetchone(),
            'artifacts': c.execute('SELECT * FROM artifacts WHERE node_run_id=%s ORDER BY id', (case.run,)).fetchall(),
            'inbox': c.execute('SELECT * FROM message_inbox WHERE consumer=%s AND message_id=%s', ('result:' + case.owner, case.run)).fetchall(),
            'outbox': c.execute('SELECT * FROM message_outbox WHERE aggregate_id=%s ORDER BY id', (case.job,)).fetchall(),
            'quarantine': c.execute('SELECT * FROM result_quarantine WHERE node_run_id=%s ORDER BY message_sha256', (case.run,)).fetchall(),
        }


def _held(db, admin, movie, tmp_path, role):
    # Three valid <=100-row ASR responses produce 201 rows for three MT batches.
    media = _long_movie(tmp_path)
    runtime, owner, seed = formal(db, admin, media, tmp_path, prepare=False)
    definition = {k: deepcopy(seed['snapshot']['definition'][k]) for k in
                  ('catalog_version', 'revision', 'name', 'inputs', 'nodes', 'edges')}
    definition['revision'] = 0
    definition['nodes'].append(dict(id='review', type='review',
                                    options={'data_type': 'transcript'}, position={'x': 1440, 'y': 50}))
    definition['edges'].append(dict(id='review-edge', source={'node': 'translate', 'port': 'transcript'},
                                   target={'node': 'review', 'port': 'value'}))
    from video_service.renewal_contracts import validate
    assert validate(definition)['valid'], validate(definition)
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    job = runtime.create(owner, seed['asset_id'], saved['id'], saved['revision'],
                         request_id=uuid4().hex, options={'source_language': 'en', 'target_language': 'ko'})

    def forbidden(*args, **kwargs):
        pytest.fail('no operating broker/provider or automatic dispatch is allowed')

    coordinator = ModelRoleCoordinator(runtime, SimpleNamespace(
        model_role_factories={'transcription': forbidden, 'translation': forbidden},
        model_role_result_store=runtime.store))
    coordinator.auto_enroll_new_job(owner, job['id'], uuid4().hex)
    roles = coordinator.roles
    admit(runtime, owner, job['id'])
    for expected in ('extract_audio', 'preprocess_audio'):
        command = runtime.claim_next(owner, job['id'])
        assert command['agent']['id'] == expected
        result = runtime.execute_command(owner, command)
        assert result['status'] == 'completed', result
        runtime.accept(owner, command, result)
    command = runtime.claim_next(owner, job['id'])
    assert command['agent']['id'] == 'transcribe'
    bridge = RoleToolBridge(roles, chunk_concurrency=1)
    calls = []
    current = SimpleNamespace(index=None, size=None, retry=False)

    class SpeechAdapter:
        def transcribe(self, model, audio, language):
            index = 1 if current.retry else current.index
            calls.append(('retry' if current.retry else 'original', 'transcription', index))
            if role == 'transcription' and index == 1 and not current.retry:
                raise EndpointFailure('synthetic known rejection', code='unavailable')
            if role == 'translation':
                # Each actual chunk respects the timed-audio 100-row bound.
                return [dict(start=i / 500, end=(i + 0.5) / 500,
                             text=f'source-{index * 67 + i}') for i in range(67)]
            return [dict(start=0.1, end=0.4, text='retry-asr' if current.retry else f'original-asr-{index}')]

        def close(self):
            pass

    class SpeechTool:
        def for_chunk(self, task, chunk, candidate):
            def invoke(model, audio, language):
                current.index = chunk['index']
                return bridge.invoke(dict(task_id=task['task_id'], chunk_index=chunk['index'],
                    candidate_index=candidate, model=model, source_language=language,
                    audio_base64=base64.b64encode(audio).decode(), **tool_context(task)))
            return invoke

    class TextAdapter:
        _client = SimpleNamespace(timeout=0)

        def chat(self, model, messages):
            index = 1 if current.retry else current.index
            calls.append(('retry' if current.retry else 'original', 'translation', index))
            if index == 1 and not current.retry:
                raise EndpointFailure('synthetic known rejection', code='unavailable')
            return json.dumps(['retry-mt' if current.retry else 'original-mt'] * (100 if current.retry else current.size))

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda pin, key: SpeechAdapter()
    runtime.translation_runtime.make_adapter = lambda pin, key: TextAdapter()

    def deliver(command, agent):
        envelope = roles.enroll(owner, command)
        assert envelope['task']['version'] == 2
        assert roles.publish_exact(owner, job['id'], command['attempt_id'], lambda _: True)
        receiver = RoleReceiver(agent, runtime.store, runtime.store)
        ack = receiver.deliver(envelope)
        before = list(calls)
        assert receiver.deliver(envelope) == ack
        assert calls == before
        roles.receive(ack)
        return envelope, ack

    envelope, ack = deliver(command, TranscriptionAgent(tmp_path / 'recovery-asr', SpeechTool(), chunk_concurrency=1))
    if role == 'translation':
        assert ack['status'] == 'completed'
        command = roles.dispatch_next(owner, job['id'])
        assert command['agent']['id'] == 'translate'

        def text_tool(task, batch, candidate):
            current.index, current.size = batch.chunk_index, len(batch.segments)
            return bridge.invoke_translation(dict(task_id=task['task_id'], batch_index=batch.chunk_index,
                candidate_index=candidate, model=task['models'][candidate], input_sha256=batch.sha256,
                **tool_context(task)))

        envelope, ack = deliver(command, TranslationAgent(tmp_path / 'recovery-mt', text_tool))
    assert ack['status'] == 'held'
    case = SimpleNamespace(runtime=runtime, owner=owner, job=job['id'], run=command['attempt_id'],
                           role=role, command=command, envelope=envelope, ack=ack,
                           calls=calls, current=current, roles=roles)
    service = RoleUnitRecovery(runtime)
    view = service.inspect(owner, case.job, case.run)
    expected = ['succeeded', 'failed', 'succeeded' if role == 'transcription' else 'unattempted']
    assert [u['status'] for u in view['units']] == expected, view
    assert view['supported'] and view['blocked_reason'] is None
    # Synthetic fault injection only in this fixture's random disposable schema.
    with db.connection() as c:
        c.execute("UPDATE node_runs SET lease_expires_at=now()-interval '1 day' WHERE id=%s", (case.run,))
        assert c.execute('SELECT lease_expires_at<now() AS expired FROM node_runs WHERE id=%s', (case.run,)).fetchone()['expired']
    return case


def _normal_downstream(case):
    """Review is an application control node, not a worker command."""
    command = case.runtime.claim_next(case.owner, case.job)
    if case.role == 'transcription':
        assert command['agent']['id'] == 'translate'
        return command
    assert command is None
    state = case.runtime.get(case.owner, case.job)
    assert state['id'] == case.job and state['status'] == 'review_required'
    reviews = [r for r in state['runs'] if r['node_id'] == 'review']
    assert len(reviews) == 1 and reviews[0]['status'] == 'review_required'
    with case.runtime.database.connection() as c:
        row = c.execute('SELECT request FROM node_runs WHERE id=%s', (reviews[0]['id'],)).fetchone()
        tasks = c.execute('SELECT * FROM review_tasks WHERE job_id=%s AND node_run_id=%s',
                          (case.job, reviews[0]['id'])).fetchall()
    assert len(tasks) == 1 and tasks[0]['status'] == 'draft'
    return row['request']


def _decisions(view, role, action, *, suffix=True):
    decision: dict = dict(unit_index=1, action=action)
    if action == 'manual':
        decision['value'] = ([dict(start=0.1, end=0.4, text='manual-asr')] if role == 'transcription'
                             else [{**r, 'text': 'manual-mt'} for r in view['units'][1]['source_rows']])
    if action == 'retry':
        decision['candidate_index'] = 0
    return [decision] + ([dict(unit_index=2, action='skip')] if role == 'translation' and suffix else [])


def _approve(service, case, decisions):
    view = service.inspect(case.owner, case.job, case.run)
    body = {k: view[k] for k in ('job_revision', 'recovery_revision', 'context_sha256')}
    body['decisions'] = decisions
    preview = service.preview(case.owner, case.job, case.run, body)
    return {**body, 'request_id': uuid4().hex, 'preview_sha256': preview['preview_sha256'], 'approve_calls': True}


@pytest.mark.parametrize('role', ['transcription', 'translation'])
@pytest.mark.parametrize('action', ['manual', 'skip', 'retry'])
def test_real_same_job_adoption_and_normal_downstream_claim(db, admin, movie, tmp_path, role, action):
    case = _held(db, admin, movie, tmp_path, role)
    runtime, owner, job, run = case.runtime, case.owner, case.job, case.run
    original = _history(case)
    before = _effects(case)
    original_calls = list(case.calls)
    retry_bridge = UnitRecoveryToolBridge(runtime, role)
    service = RoleUnitRecovery(runtime, executor=lambda attempt, context:
        retry_bridge.invoke({'attempt_id': attempt, 'context_sha256': context}))
    view = service.inspect(owner, job, run)
    decisions = _decisions(view, role, action)

    # Real API serialization + persisted service. Saving and GET cannot call tools
    # or continue the job; there is intentionally no broker in this test.
    app = FastAPI()
    dispatches = []
    mount_unit_recovery_routes(app, runtime, Depends(lambda: owner),
                               continue_job=lambda *args: dispatches.append(args))
    base = f'/api/renewal/jobs/{job}/runs/{run}/unit-recovery'
    body = _approve(service, case, decisions)
    with TestClient(app) as client:
        response = client.post(base + '/decisions', json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert client.post(base + '/decisions', json=body).json() == saved
        assert client.get(base).status_code == 200
        assert client.get(base).json()['recovery']['id'] == saved['recovery']['id']
    assert case.calls == original_calls and dispatches == []
    assert _effects(case) == before
    assert _history(case) == original
    assert saved['recovery']['additional_call_limit'] == (1 if action == 'retry' else 0)

    case.current.retry = True
    executed = service.execute(owner, job, run, body['request_id'])
    assert executed['recovery']['can_continue'], executed
    after_calls = original_calls + ([('retry', role, 1)] if action == 'retry' else [])
    assert case.calls == after_calls
    service.execute(owner, job, run, body['request_id'])
    assert case.calls == after_calls
    prepared = service.prepare_adoption(owner, job, run, body['request_id'])
    assert _history(case) == original
    adopted = runtime.accept_role_recovery(owner, job, run, body['request_id'])
    assert adopted['id'] == job and adopted['revision'] == before['job']['revision'] + 1
    after = _effects(case)
    receipt = after['run']['result']
    assert after['run']['status'] == 'completed'
    assert receipt['transport'] == 'application_unit_recovery'
    assert receipt['unit_recovery']['id'] == saved['recovery']['id']
    assert receipt['unit_recovery']['resolution_origin'] == 'explicit_user_decisions'
    assert receipt['outputs'] == prepared['outputs']
    assert after['run']['lease_expires_at'] == before['run']['lease_expires_at']
    assert after['run']['request'] == before['run']['request']
    assert after['run']['request_sha256'] == before['run']['request_sha256']
    assert _history(case) == original
    assert len(after['inbox']) == 1 and after['inbox'][0]['payload_sha256'] == digest(receipt)
    assert len(after['outbox']) == len(before['outbox']) + 1
    previous_messages = {message['id'] for message in before['outbox']}
    accepted = [message for message in after['outbox'] if message['id'] not in previous_messages]
    assert len(accepted) == 1 and accepted[0]['message_type'] == 'agent.result.accepted.v1'
    assert accepted[0]['payload'] == dict(job_id=job, node_run_id=run,
        generation=case.command['generation'], quarantined=False, unit_recovery_id=saved['recovery']['id'])
    assert after['quarantine'] == before['quarantine'] == []
    assert len(after['artifacts']) == len(receipt['outputs'])
    assert adopted['artifact_manifest']['layout'] == 'ticket_v1'
    entries = receipt['ticket_artifacts']['entries']
    assert len(entries) == len(receipt['outputs'])
    for entry in entries:
        assert entry['ticket_id'] == job and entry['node_run_id'] == run
        assert entry['storage']['storage_key'].startswith(f'tickets/{job}/')
        assert runtime.store.read(owner, entry['storage']) == runtime.store.read(owner, entry['reference'])
        assert any(a['storage_key'] == entry['storage']['storage_key'] and a['sha256'] == entry['storage']['sha256'] for a in after['artifacts'])
    with db.connection() as c:
        recovery = c.execute('SELECT * FROM model_role_unit_recoveries WHERE id=%s', (saved['recovery']['id'],)).fetchone()
        attempts = c.execute('SELECT * FROM model_role_unit_attempts WHERE recovery_id=%s', (recovery['id'],)).fetchall()
    assert recovery['status'] == 'applied' and recovery['receipt_sha256'] == digest(receipt)
    assert len(attempts) == (1 if action == 'retry' else 0)
    if attempts:
        assert attempts[0]['status'] == 'completed' and attempts[0]['unit_index'] == 1
    output_port = 'transcript'
    from video_service.renewal_contracts import catalog
    node_type = 'transcribe' if role == 'transcription' else 'translate'
    assert output_port in next(n for n in catalog()['nodes'] if n['id'] == node_type)['outputs']
    rows = json.loads(runtime.store.read(owner, receipt['outputs'][output_port]))
    if role == 'transcription':
        assert [r['text'] for r in rows] == (['original-asr-0', 'original-asr-2'] if action == 'skip'
            else ['original-asr-0', f'{action}-asr', 'original-asr-2'])
        assert rows[-1]['start'] >= 120
    else:
        assert len(rows) == (100 if action == 'skip' else 200)
        source = json.loads(runtime.store.read(owner, case.command['inputs']['transcript']))
        assert [{k: v for k, v in r.items() if k != 'text'} for r in rows] == [
            {k: v for k, v in r.items() if k != 'text'} for r in source[:len(rows)]]
        assert all(r['text'] == 'original-mt' for r in rows[:100])
        assert all(r['text'] == f'{action}-mt' for r in rows[100:])
    # Applied replay is a read, not a second result/outbox/artifact or revision.
    assert runtime.accept_role_recovery(owner, job, run, body['request_id']) == adopted
    assert _effects(case) == after and case.calls == after_calls
    # Both old role transport and ordinary node-result transport are fenced.
    with pytest.raises(Conflict):
        case.roles.receive({**case.ack, 'status': 'completed'})
    late = deepcopy(receipt)
    late.pop('unit_recovery')
    late['transport'] = 'independent_model_role'
    with pytest.raises(Conflict):
        runtime.accept(owner, case.command, late)
    assert _effects(case) == after and _history(case) == original
    downstream = _normal_downstream(case)
    assert downstream['run_id'] == job
    assert downstream['agent']['id'] == ('translate' if role == 'transcription' else 'review')
    assert downstream['inputs']['transcript' if role == 'transcription' else 'value'] == receipt['outputs'][output_port]
    assert case.calls == after_calls
    with db.connection() as c:
        earlier = c.execute('SELECT * FROM node_runs WHERE job_id=%s AND id<>%s AND id<>%s ORDER BY id',
                            (job, run, downstream['attempt_id'])).fetchall()
    assert earlier == original[3]


@pytest.mark.parametrize('role', ['transcription', 'translation'])
@pytest.mark.parametrize('damage', ['cancel', 'stale_revision'])
def test_real_adoption_rejects_cancelled_or_stale_context(db, admin, movie, tmp_path, role, damage):
    case = _held(db, admin, movie, tmp_path, role)
    service = RoleUnitRecovery(case.runtime)
    view = service.inspect(case.owner, case.job, case.run)
    body = _approve(service, case, _decisions(view, role, 'manual'))
    service.decide(case.owner, case.job, case.run, body)
    service.prepare_adoption(case.owner, case.job, case.run, body['request_id'])
    calls = list(case.calls)
    if damage == 'cancel':
        state = case.runtime.get(case.owner, case.job)
        case.runtime.cancel(case.owner, case.job, state['revision'])
    else:
        # Explicit synthetic stale-CAS fault, in the disposable schema only.
        with db.connection() as c:
            c.execute('UPDATE jobs SET revision=revision+1 WHERE id=%s', (case.job,))
    before = _effects(case)
    with pytest.raises(Conflict):
        case.runtime.accept_role_recovery(case.owner, case.job, case.run, body['request_id'])
    assert _effects(case) == before
    assert before['run']['result'] is None
    assert before['artifacts'] == before['inbox'] == []
    assert case.calls == calls


def test_real_partial_retry_requires_explicit_mt_suffix_before_adoption(db, admin, movie, tmp_path):
    case = _held(db, admin, movie, tmp_path, 'translation')
    bridge = UnitRecoveryToolBridge(case.runtime, case.role)
    service = RoleUnitRecovery(case.runtime, executor=lambda attempt, context:
        bridge.invoke({'attempt_id': attempt, 'context_sha256': context}))
    original = _history(case)
    calls = list(case.calls)
    view = service.inspect(case.owner, case.job, case.run)
    first = _approve(service, case, _decisions(view, case.role, 'retry', suffix=False))
    service.decide(case.owner, case.job, case.run, first)
    case.current.retry = True
    state = service.execute(case.owner, case.job, case.run, first['request_id'])
    assert not state['recovery']['can_continue']
    assert [u['status'] for u in state['units']] == ['succeeded', 'succeeded', 'unattempted']
    with pytest.raises(Conflict):
        case.runtime.accept_role_recovery(case.owner, case.job, case.run, first['request_id'])
    second = _approve(service, case, [dict(unit_index=2, action='skip')])
    state = service.decide(case.owner, case.job, case.run, second)
    assert state['recovery']['additional_call_limit'] == 0
    assert state['recovery']['can_continue']
    service.execute(case.owner, case.job, case.run, second['request_id'])
    adopted = case.runtime.accept_role_recovery(case.owner, case.job, case.run, second['request_id'])
    assert adopted['id'] == case.job
    assert case.calls == calls + [('retry', 'translation', 1)]
    assert _history(case) == original
    receipt = _effects(case)['run']['result']
    rows = json.loads(case.runtime.store.read(case.owner, receipt['outputs']['transcript']))
    assert len(rows) == 200 and all(r['text'] == 'retry-mt' for r in rows[100:])
    assert len(receipt['unit_recovery']['reused_attempts']) == 1
    following = _normal_downstream(case)
    assert following['agent']['id'] == 'review' and following['run_id'] == case.job
