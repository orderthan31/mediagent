"""Actual media boundaries and NOWAIT row locks on disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4

import pytest
from test_execution import db, admin, movie, runtime, setup, graph
from test_start_requests import saved_case, progress
from video_service.postgres import Conflict


@pytest.mark.parametrize('phase', ['enrolled', 'planned', 'confirmed'])
def test_actual_generic_path_leaves_job_and_intent_unlocked(runtime, admin, movie, monkeypatch, phase):
    service, owner, job, rid = saved_case(runtime, admin, movie)
    progress(service, owner, rid, phase)
    entered, release = threading.Event(), threading.Event()
    original = runtime.store.path
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime.store, 'path', blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.process, owner, rid)
        try:
            assert entered.wait(10), 'actual content verification was not reached'
            with runtime.database.connection() as c:
                c.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
                c.execute('SELECT id FROM message_outbox WHERE id=%s FOR UPDATE NOWAIT', (rid,))
            assert service.cancel(owner, rid)['state'] == 'cancelled'
        finally:
            release.set()
            pending.result(timeout=20)
    assert service.get(owner, rid)['state'] == 'cancelled'
    assert runtime.get(owner, job['id'])['status'] == 'draft'
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 0
        expected = 1 if phase == 'confirmed' else 0
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == expected
        assert c.execute('SELECT count(*) n FROM execution_consents WHERE consumed_at IS NOT NULL').fetchone()['n'] == 0


@pytest.mark.parametrize('operation', ['plan', 'confirm', 'admit'])
def test_legacy_path_fresh_revision_rejects_stale_mutation(runtime, admin, movie, monkeypatch, operation):
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie, graph('analyze'))
    plan = runtime.plan(owner, job['id'])
    consent = runtime.confirm(owner, job['id'], plan['token'], uuid4().hex) if operation == 'admit' else None
    entered, release = threading.Event(), threading.Event()
    original = runtime.store.path
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime.store, 'path', blocked)
    def work():
        if operation == 'plan':
            return runtime.plan(owner, job['id'])
        if operation == 'confirm':
            return runtime.confirm(owner, job['id'], plan['token'], uuid4().hex)
        return runtime.admit(owner, job['id'], consent['id'], uuid4().hex)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(work)
        try:
            assert entered.wait(10)
            with runtime.database.connection() as c:
                c.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
                c.execute('UPDATE jobs SET revision=revision+1,cancel_requested=true WHERE id=%s', (job['id'],))
        finally:
            release.set()
        if operation == 'plan':
            assert not pending.result(timeout=20)['ready']
        else:
            with pytest.raises(Conflict):
                pending.result(timeout=20)
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_claims').fetchone()['n'] == 0
        assert c.execute('SELECT count(*) n FROM execution_consents WHERE consumed_at IS NOT NULL').fetchone()['n'] == 0


def accepted_audio_case(db, admin, movie, tmp_path):
    from test_model_role_orchestration import formal
    from test_execution import admit
    from mideagent_orchestrator.workflow import default_definition
    rt, owner, old = formal(db, admin, movie, tmp_path, prepare=False)
    saved = rt.save_definition(owner, uuid4().hex, graph('extract_audio'))
    seed = rt.create(owner, old['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex)
    admit(rt, owner, seed['id'])
    seed = rt.run_local(owner, seed['id'])
    assert seed['status'] == 'completed'
    definition = default_definition()
    model = next(n['model_ref'] for n in old['snapshot']['definition']['nodes'] if n['type'] == 'transcribe')
    definition.update(inputs={'audio': 'audio'}, nodes=[{**definition['nodes'][0], 'model_ref': model,
        'options': {'audio_source': 'selected_audio', 'source_language': 'en'}}], edges=[])
    saved = rt.save_definition(owner, uuid4().hex, definition)
    options = {'source_language': 'en', 'accepted_inputs': {'audio': {
        'job_id': seed['id'], 'run_id': seed['runs'][0]['id'], 'port': 'audio'}}}
    return rt, owner, seed, saved, options


@pytest.mark.parametrize('boundary', ['artifact', 'path', 'wav', 'later_root'])
def test_accepted_audio_io_unlocked_and_source_removal_fences_creation(db, admin, movie, tmp_path, monkeypatch, boundary):
    import mideagent_orchestrator.normal_inputs as normal
    rt, owner, seed, saved, options = accepted_audio_case(db, admin, movie, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def pause(original):
        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)
        return blocked
    if boundary == 'artifact':
        monkeypatch.setattr(rt.ticket_artifacts, 'read', pause(rt.ticket_artifacts.read))
    elif boundary == 'wav':
        monkeypatch.setattr(normal, 'verify_raw_wav', pause(normal.verify_raw_wav))
    else:
        original = rt.store.path
        def selected(owner_id, reference):
            if (boundary == 'path' and reference['type'] == 'audio') or (boundary == 'later_root' and reference['type'] == 'video'):
                entered.set()
                assert release.wait(10)
            return original(owner_id, reference)
        monkeypatch.setattr(rt.store, 'path', selected)
    nonce = uuid4().hex
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(rt.create, owner, seed['asset_id'], saved['id'], saved['revision'], request_id=nonce, options=options)
        try:
            assert entered.wait(10)
            with rt.database.connection() as c:
                c.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (seed['id'],))
                c.execute("UPDATE jobs SET library_removed_at=now(),library_removed_by=%s,library_removal_reason='synthetic removal' WHERE id=%s", (owner, seed['id']))
        finally:
            release.set()
        with pytest.raises((ValueError, Conflict)):
            pending.result(timeout=20)
    with rt.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs WHERE creation_request_id=%s', (nonce,)).fetchone()['n'] == 0


def accepted_transcript_case(db, admin, movie, tmp_path):
    from test_execution import admit
    from test_transcription_execution import audio_graph
    from test_normal_inputs import input_graph

    rt, owner, audio, saved, _ = accepted_audio_case(db, admin, movie, tmp_path)
    model = rt.job_definition(owner, saved['id'], saved['revision'])['nodes'][0]['model_ref']
    native = audio_graph(model, model)
    native['nodes'] = native['nodes'][:-1]
    native['edges'] = native['edges'][:-1]

    definition = rt.save_definition(owner, uuid4().hex, native)
    seed = rt.create(owner, audio['asset_id'], definition['id'], definition['revision'],
        request_id=uuid4().hex, options={'source_language': 'en'})
    calls = []
    admit(rt, owner, seed['id'])
    # Synthetic inference only. Actual PCM validation, finite candidate runner,
    # SQL delivery/receipt adoption and ticket artifact publication remain real.
    class ControlledInference:
        def close(self):
            pass

        def transcribe(self, model, audio, language):
            calls.append(model)
            return [{'start': 0.1, 'end': 0.4, 'text': 'Controlled synthetic transcript'}]
    rt.transcription_runtime.make_adapter = lambda pin, key: ControlledInference()
    seed = rt.run_local(owner, seed['id'])
    assert seed['status'] == 'completed', [(r['node_type'], r['status'], r.get('result')) for r in seed['runs']]
    assert len(calls) == 1
    run = next(r for r in seed['runs'] if r['node_type'] == 'transcribe')
    target = input_graph()
    target['revision'] = 0
    saved = rt.save_definition(owner, uuid4().hex, target)
    options = {'accepted_inputs': {'transcript': {'job_id': seed['id'], 'run_id': run['id'], 'port': 'transcript'}}}
    return rt, owner, seed, saved, options


@pytest.mark.parametrize('port', ['audio', 'transcript'])
def test_accepted_positive_preview_create_plan_preserves_exact_pins(db, admin, movie, tmp_path, port):
    from video_service.canonical import digest
    case = accepted_audio_case if port == 'audio' else accepted_transcript_case
    rt, owner, seed, saved, options = case(db, admin, movie, tmp_path)
    definition = rt.job_definition(owner, saved['id'], saved['revision'])
    resolved = rt.normal_input_plan(owner, seed['asset_id'], definition, options)
    job = rt.create(owner, seed['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex,
        options=options, input_plan_sha256=digest(resolved['bindings']))
    assert job['snapshot']['normal_input_bindings'] == resolved['bindings']
    assert job['snapshot']['inputs'][port] == resolved['references'][port]
    assert rt.plan(owner, job['id'])['ready']
    assert job['snapshot']['normal_input_bindings'][port]['job_id'] == seed['id']


@pytest.mark.parametrize('mutation', ['removed', 'revision', 'receipt', 'request'])
def test_accepted_transcript_read_unlocked_and_fresh_metadata_fenced(db, admin, movie, tmp_path, monkeypatch, mutation):
    rt, owner, seed, saved, options = accepted_transcript_case(db, admin, movie, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = rt.store.read
    def blocked(owner_id, reference, **kwargs):
        if reference['type'] == 'transcript':
            entered.set()
            assert release.wait(10)
        return original(owner_id, reference, **kwargs)
    monkeypatch.setattr(rt.store, 'read', blocked)
    nonce = uuid4().hex
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(rt.create, owner, seed['asset_id'], saved['id'], saved['revision'], request_id=nonce, options=options)
        try:
            assert entered.wait(10)
            with rt.database.connection() as c:
                c.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (seed['id'],))
                if mutation == 'removed':
                    c.execute("UPDATE jobs SET library_removed_at=now(),library_removed_by=%s,library_removal_reason='synthetic removal' WHERE id=%s", (owner, seed['id']))
                elif mutation == 'revision':
                    c.execute('UPDATE jobs SET revision=revision+1 WHERE id=%s', (seed['id'],))
                elif mutation == 'receipt':
                    c.execute("UPDATE node_runs SET result=jsonb_set(result,'{status}','\"unknown\"') WHERE id=%s", (options['accepted_inputs']['transcript']['run_id'],))
                else:
                    c.execute("UPDATE node_runs SET request_sha256=%s WHERE id=%s", ('f' * 64, options['accepted_inputs']['transcript']['run_id']))
        finally:
            release.set()
        with pytest.raises((ValueError, Conflict)):
            pending.result(timeout=20)
    with rt.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM jobs WHERE creation_request_id=%s', (nonce,)).fetchone()['n'] == 0


def test_accepted_raw_preview_cancel_has_no_job_or_late_consent(db, admin, movie, tmp_path, monkeypatch):
    from test_start_requests_api import actual_client, raw_request
    rt, owner, seed, saved, options = accepted_audio_case(db, admin, movie, tmp_path)
    client, service = actual_client(rt, admin)
    body = raw_request(client, {'asset_id': seed['asset_id']}, saved, options)
    rid = service.submit_raw(owner, body)['id']
    entered, release = threading.Event(), threading.Event()
    original = service.runtime.ticket_artifacts.read
    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(service.runtime.ticket_artifacts, 'read', blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.process, owner, rid)
        try:
            assert entered.wait(10), service.get(owner, rid)
            with rt.database.connection() as c:
                c.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (seed['id'],))
                c.execute('SELECT id FROM message_outbox WHERE id=%s FOR UPDATE NOWAIT', (rid,))
            assert service.cancel(owner, rid)['state'] == 'cancelled'
        finally:
            release.set()
            pending.result(timeout=20)
    assert service.get(owner, rid)['state'] == 'cancelled'
    assert service.get(owner, rid)['job_id'] is None


@pytest.mark.parametrize('kind', ['video', 'subtitle'])
def test_generic_content_corruption_remains_fail_closed(runtime, admin, movie, kind):
    owner = admin[0]['id']
    if kind == 'video':
        _, _, job = setup(runtime, owner, movie, graph('analyze'))
    else:
        from test_subtitle_original_input import text_definition, SRT
        source = runtime.ingest(owner, 'synthetic.srt', SRT.encode())
        saved = runtime.save_definition(owner, uuid4().hex, text_definition())
        job = runtime.create(owner, source['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex)
    reference = next(iter(job['snapshot']['inputs'].values()))
    path = runtime.store.path(owner, reference)
    path.write_bytes(b'corrupt synthetic content')
    with pytest.raises((ValueError, Conflict)):
        runtime.plan(owner, job['id'])
    with runtime.database.connection() as c:
        assert c.execute('SELECT count(*) n FROM execution_consents').fetchone()['n'] == 0


def test_unissued_verification_dictionary_cannot_bypass_locked_validator(runtime, admin, movie):
    from video_service.canonical import digest
    owner = admin[0]['id']
    _, _, job = setup(runtime, owner, movie, graph('analyze'))
    verified = runtime._preflight_cpu_inputs(owner, job['id'])
    with runtime.database.connection() as c:
        row = runtime._job(c, owner, job['id'], lock=True)
        reference = next(iter(row['snapshot']['inputs'].values()))
        assert digest(reference) in verified['references']
        with pytest.raises(Conflict):
            runtime._checked_input(owner, row, reference, dict(verified))
