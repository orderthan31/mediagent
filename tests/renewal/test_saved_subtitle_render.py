"""Saved-copy render connection: synthetic inputs, temporary CAS, no operating I/O."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from test_goal_corrections import source_execution
from test_goal_recovery_policy import recovery_runtime, historical_chain
from test_normal_inputs import mount_actual_input_handlers

ROOT = Path(__file__).resolve().parents[2]
for project in ('packages/shared', 'agents', 'apps/orchestrator'):
    sys.path.insert(0, str(ROOT / project))

OWNER, ACTOR, COPY = 'a' * 32, 'b' * 32, 'c' * 32
SRT = '\ufeff  \r\n00:00:00,125 --> 00:00:01,750\r\n literal <text> \r\nsecond line\r\n\r\ncue A\r\n00:00:01,000 --> 00:00:02,800\r\noverlap\r\n'
SHA = hashlib.sha256(SRT.encode()).hexdigest()


def selection(**options):
    return {'saved_subtitle': {'copy_id': COPY, 'srt_sha256': SHA},
            'render_goal': {'node_id': 'subtitle_video', 'options': options}, 'input_language': 'en'}


def source_graph():
    from mideagent_orchestrator.workflow import default_definition
    return default_definition()


@pytest.fixture
def state(tmp_path, monkeypatch):
    from video_service.content_store import ContentStore
    from video_service.subtitle_copies import SubtitleCopies
    if os.name == 'nt':
        chmod = Path.chmod
        def mode(path, value, *args, **kwargs):
            if value == 0o400 and path.is_relative_to(tmp_path):
                return
            return chmod(path, value, *args, **kwargs)
        monkeypatch.setattr(Path, 'chmod', mode)
    store = ContentStore(tmp_path)
    copies = SubtitleCopies(store)
    copies.save(OWNER, id=COPY, filename='actual-name.smi', title='Saved edit', srt=SRT)
    return SimpleNamespace(store=store, copies=copies,
                           asset={'metadata': {'media': {'duration': 12.0}}})


def test_real_saved_agent_is_narrowed_without_asr_mt_or_source_mutation():
    from mideagent_orchestrator.workflow import render_definition, compile_definition
    graph = source_graph()
    before = deepcopy(graph)
    effective = render_definition(graph, selection(video_codec='hevc', subtitle_mode='soft'))
    assert graph == before and effective['revision'] == graph['revision']
    assert [n['type'] for n in effective['nodes']] == ['subtitle_video_agent']
    native = compile_definition(effective)['definition']
    assert [n['type'] for n in native['nodes']] == ['generate_subtitle', 'encode', 'validate_video']
    assert native['nodes'][1]['options']['video_codec'] == 'hevc'
    assert native['nodes'][1]['options']['subtitle_mode'] == 'soft'
    assert all('model_ref' not in n for n in native['nodes'])
    assert render_definition(graph, {}) == graph
    for bad in ({'node_id': 'translation', 'options': {}},
                {'node_id': 'subtitle_video', 'options': {'font': 'invented'}},
                {'node_id': 'subtitle_video', 'options': {'video_codec': 'bad'}}):
        with pytest.raises(ValueError):
            render_definition(graph, {**selection(), 'render_goal': bad})


def test_saved_resolution_is_read_only_and_create_materializes_under_real_custodian(state, monkeypatch):
    from mideagent_orchestrator.workflow import render_definition, compile_definition
    from mideagent_orchestrator.normal_inputs import NormalInputs, public_input_summary
    from video_service.canonical import canonical, digest
    from video_service.content_store import reference_origin
    from video_service.timed_subtitles import preserved_files
    resolver = NormalInputs(SimpleNamespace(store=state.store))
    graph = render_definition(source_graph(), selection())
    put = state.store.put
    monkeypatch.setattr(state.store, 'put', lambda *a, **k: pytest.fail('preview wrote CAS'))
    resolved = resolver.resolve(None, ACTOR, state.asset, graph, selection())
    rows = resolved['segments']
    assert rows == [{'id': '  ', 'start': .125, 'end': 1.75, 'text': ' literal <text> \nsecond line'},
                    {'id': 'cue A', 'start': 1.0, 'end': 2.8, 'text': 'overlap'}]
    pin = resolved['bindings']['transcript']
    assert pin['kind'] == 'saved_subtitle' and pin['copy_id'] == COPY
    assert pin['custodian_id'] == OWNER and pin['source_sha256'] == SHA
    assert pin['content_sha256'] == digest(rows)
    opened = state.copies.get(COPY)
    assert opened['srt_sha256'] == SHA and 'actor_id' not in opened and 'reference' not in opened
    public = public_input_summary(resolved['bindings'])
    assert public[0]['copy_id'] == COPY and 'custodian_id' not in str(public) and 'storage_key' not in str(public)
    native = compile_definition(graph, input_language=resolved['language'])['definition']
    generator = native['nodes'][0]
    assert generator['options']['cue_policy'] == 'preserve_v1'
    files = preserved_files(rows, generator['options'])
    assert files['subtitles'] == SRT.removeprefix('\ufeff').replace('\r\n', '\n').encode()
    assert any(e['source'] == {'node': generator['id'], 'port': 'subtitles'} and e['target']['port'] == 'subtitles' for e in native['edges'])
    writes = []
    def materialize(owner, blocks, kind):
        writes.append((owner, kind))
        return put(owner, blocks, kind)
    monkeypatch.setattr(state.store, 'put', materialize)
    refs = resolver.materialize(ACTOR, resolved)
    assert writes == [(OWNER, 'transcript')]
    owner, ref = reference_origin(ACTOR, refs['transcript'])
    assert owner == OWNER and state.store.read(owner, ref) == canonical(rows)
    assert state.copies.get(COPY)['srt'] == SRT


@pytest.mark.parametrize('change', ['missing', 'hash', 'storage_key', 'mix', 'duration', 'unknown_duration'])
def test_bad_saved_selection_never_becomes_empty_ready_or_writes(state, monkeypatch, change):
    from mideagent_orchestrator.workflow import render_definition
    from mideagent_orchestrator.normal_inputs import NormalInputs
    opts = selection()
    graph = render_definition(source_graph(), opts)
    if change == 'missing': opts['saved_subtitle']['copy_id'] = 'd' * 32
    if change == 'hash': opts['saved_subtitle']['srt_sha256'] = '0' * 64
    if change == 'storage_key': opts['saved_subtitle']['storage_key'] = 'private'
    if change == 'mix': opts['subtitle_srt'] = SRT
    if change == 'duration': state.asset['metadata']['media']['duration'] = 2.0
    if change == 'unknown_duration': state.asset['metadata']['media'] = {}
    monkeypatch.setattr(state.store, 'put', lambda *a, **k: pytest.fail('invalid input wrote CAS'))
    with pytest.raises((ValueError, FileNotFoundError)):
        NormalInputs(SimpleNamespace(store=state.store)).resolve(None, ACTOR, state.asset, graph, opts)


@pytest.fixture
def connected(state, recovery_runtime):
    graph = source_graph()
    graph['revision'] = 1
    _, parent = historical_chain()
    runtime = recovery_runtime(graph, parent)
    runtime.store = state.store
    video = state.store.put(OWNER, [b'synthetic video descriptor, never executed'], 'video')
    asset = {'id': 'd' * 32, 'owner_id': OWNER, 'bytes': video['bytes'],
             'metadata': {'registration_state': 'verified', 'media': {'duration': 12.0}}}
    runtime._shared_asset = lambda *a: deepcopy(asset)
    runtime.asset_reference = lambda *a: deepcopy(video)
    runtime.asset = lambda actor, id: {'asset_id': id, 'size_bytes': video['bytes'], 'content_verified': True, 'media': {'duration': 12.0}}
    runtime.asset_path = lambda *a: None
    runtime.job_definition = lambda *a: deepcopy(graph)
    runtime._bindings = lambda *a, **k: {}
    runtime._execution_reasons = lambda *a, **k: []
    runtime._shared_view = lambda job, actor: job
    runtime.transcription_runtime = runtime.translation_runtime = runtime.vocalization_runtime = None
    return runtime, graph, parent


def test_actual_preview_create_freezes_independent_lineage_new_job_no_admission(state, connected, monkeypatch):
    from video_service.canonical import digest, canonical
    from video_service.content_store import reference_origin
    runtime, graph, parent = connected
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id='d' * 32, definition_id=parent['workflow_id'], definition_revision=1, options=selection())
    put, writes = state.store.put, []
    def spy(*a, **k):
        writes.append(a[0])
        return put(*a, **k)
    monkeypatch.setattr(state.store, 'put', spy)
    before = deepcopy(parent)
    plan = handlers['preview'](handlers['Selection'](**args), ACTOR)
    assert plan['paid_roles'] == [] and plan['model_call_budgets'] == []
    assert not writes and not runtime.database.children and not runtime.database.outbox
    create = handlers['Create'](**args, token=plan['token'], request_id='synthetic-saved-render')
    child = handlers['create'](create, ACTOR)
    snapshot = child['snapshot']
    assert child['id'] not in {parent['id'], COPY} and child['parent_id'] is None
    assert child['status'] == 'draft' and child['active_claim_id'] is None
    assert child['workflow_id'] == parent['workflow_id']
    assert snapshot['source_definition_sha256'] == digest(graph)
    assert snapshot['render_selection'] == {'version': 1, 'node_id': 'subtitle_video', 'source_definition_sha256': digest(graph)}
    assert digest(snapshot['definition']) == plan['execution_definition_sha256']
    assert [n['type'] for n in snapshot['definition']['nodes']] == ['generate_subtitle', 'encode', 'validate_video']
    assert snapshot['normal_input_bindings']['transcript']['custodian_id'] == OWNER
    assert snapshot['normal_input_bindings']['transcript']['copy_id'] == COPY
    custodian, ref = reference_origin(ACTOR, snapshot['inputs']['transcript'])
    assert custodian == OWNER
    assert state.store.read(custodian, ref) == canonical(runtime.normal_input_plan(ACTOR, 'd' * 32, snapshot['agent_definition'], selection())['segments'])
    assert snapshot['inputs']['video']['source_owner_id'] == OWNER
    assert snapshot['role_policy_version'] == 2 and 'new_start_queue' not in snapshot
    reopened = runtime.__class__._shared_view(deepcopy(child), ACTOR)
    assert reopened['selected_inputs'][0]['copy_id'] == COPY
    assert reopened['selected_inputs'][0]['filename'] == 'actual-name.smi'
    assert 'custodian_id' not in repr(reopened['selected_inputs'])
    assert writes == [OWNER] and parent == before and not runtime.database.outbox
    assert handlers['create'](create, ACTOR)['id'] == child['id']
    assert len(runtime.database.children) == 1 and writes == [OWNER]


@pytest.mark.parametrize('change', ['video', 'copy', 'options', 'language', 'definition'])
def test_real_create_rejects_stale_preview_before_materializing(state, connected, monkeypatch, change):
    runtime, graph, parent = connected
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id='d' * 32, definition_id=parent['workflow_id'], definition_revision=1, options=selection())
    plan = handlers['preview'](handlers['Selection'](**args), ACTOR)
    if change == 'video': args['asset_id'] = 'e' * 32
    if change == 'copy':
        state.copies.save(OWNER, id='f' * 32, filename='same.srt', title='another identity', srt=SRT)
        args['options']['saved_subtitle']['copy_id'] = 'f' * 32
    if change == 'options': args['options']['render_goal']['options']['quality_profile'] = 'high'
    if change == 'language': args['options']['input_language'] = 'pt-BR'
    if change == 'definition': graph['nodes'][0]['options']['source_language'] = 'ja'
    monkeypatch.setattr(state.store, 'put', lambda *a, **k: pytest.fail('stale create wrote CAS'))
    with pytest.raises(ValueError, match='변경'):
        handlers['create'](handlers['Create'](**args, token=plan['token'], request_id='stale'), ACTOR)
    assert not runtime.database.children and not runtime.database.outbox


@pytest.mark.parametrize('language,base', [('en', 'en'), ('pt-BR', 'pt'), ('auto', 'und')])
def test_frozen_command_reads_real_origin_and_native_caption_serializer_without_render(state, connected, monkeypatch, tmp_path, language, base):
    from video_service.rabbitmq_transport import validate_command
    sys.path.insert(0, str(ROOT / 'tools/media'))
    from mideagent_media_tools import operations
    runtime, graph, parent = connected
    handlers = mount_actual_input_handlers(runtime)
    opts = selection(subtitle_mode='soft')
    opts['input_language'] = language
    args = dict(asset_id='d' * 32, definition_id=parent['workflow_id'], definition_revision=1, options=opts)
    plan = handlers['preview'](handlers['Selection'](**args), ACTOR)
    child = handlers['create'](handlers['Create'](**args, token=plan['token'], request_id='caption-only-unit'), ACTOR)
    snapshot = child['snapshot']
    generator, encoder, _ = snapshot['definition']['nodes']
    _, command = runtime._insert_run(runtime.database, child, generator, {'transcript': snapshot['inputs']['transcript']}, 'running')
    validate_command(command)
    assert command['options']['language'] == base
    assert snapshot['normal_input_bindings']['transcript']['language'] == language
    assert command['inputs']['transcript']['source_owner_id'] == OWNER
    monkeypatch.setattr(operations.subprocess, 'run', lambda *a, **k: pytest.fail('no renderer/process may run'))
    # Only the caption serializer runs on synthetic temporary bytes. No encoder,
    # ffprobe, media process, broker, model or actual job execution is invoked.
    output = tmp_path / 'caption-output'
    output.mkdir()
    result = operations.run(command, state.store.owner_root(ACTOR), output, agent='generate_subtitle')
    assert result['status'] == 'completed', result
    caption = (output / result['outputs']['subtitles']['storage_key']).read_bytes()
    assert caption == SRT.removeprefix('\ufeff').replace('\r\n', '\n').encode()
    subtitle = state.store.put(ACTOR, [caption], 'subtitle')
    _, encode_command = runtime._insert_run(runtime.database, child, encoder,
        {'video': snapshot['inputs']['video'], 'subtitles': subtitle}, 'running')
    validate_command(encode_command)
    assert encode_command['inputs']['subtitles'] == subtitle
    assert encode_command['inputs']['video']['source_owner_id'] == OWNER
    assert encode_command['options']['subtitle_mode'] == 'soft'
    assert not runtime.database.outbox


def test_render_selection_absent_keeps_existing_inline_policy(state):
    from mideagent_orchestrator.workflow import render_definition, compile_definition
    from mideagent_orchestrator.normal_inputs import NormalInputs
    graph = source_graph()
    before = deepcopy(graph)
    assert render_definition(graph, {}) == graph == before
    assert all('cue_policy' not in n['options'] for n in compile_definition(graph)['definition']['nodes'])
    inline = {'catalog_version': 2, 'revision': 1, 'name': 'existing timed input', 'inputs': {'transcript': 'transcript'},
              'nodes': [graph['nodes'][-1]], 'edges': []}
    rows = NormalInputs(SimpleNamespace(store=state.store)).resolve(None, ACTOR, {}, inline,
        {'subtitle_srt': '007\n00:00:00,125 --> 00:00:01,750\n old input \n'})
    assert rows['segments'][0]['id'] == '007'
    assert rows['bindings']['transcript']['kind'] == 'subtitle_srt'


def test_producer_long_canonical_integer_id_is_preserved_exactly(state):
    from mideagent_orchestrator.workflow import render_definition, compile_definition
    from mideagent_orchestrator.normal_inputs import NormalInputs
    from video_service.timed_subtitles import preserved_files
    cue_id = '1234567890' * 20
    srt = cue_id + '\n00:00:00,125 --> 00:00:01,750\n text \n'
    state.copies.save(OWNER, id='e' * 32, filename='literal.srt', title='producer numeric ID', srt=srt)
    opts = selection()
    opts['saved_subtitle'] = {'copy_id': 'e' * 32, 'srt_sha256': hashlib.sha256(srt.encode()).hexdigest()}
    graph = render_definition(source_graph(), opts)
    resolved = NormalInputs(SimpleNamespace(store=state.store)).resolve(None, ACTOR, state.asset, graph, opts)
    generator = compile_definition(graph, input_language='en')['definition']['nodes'][0]
    assert preserved_files(resolved['segments'], generator['options'])['subtitles'] == srt.encode()


def test_saved_input_retains_native_sami_overlap_and_consumer_size_errors(state):
    from mideagent_orchestrator.workflow import render_definition
    from mideagent_orchestrator.normal_inputs import NormalInputs
    resolver = NormalInputs(SimpleNamespace(store=state.store))
    opts = selection(format='srt_smi')
    with pytest.raises(ValueError):
        resolver.resolve(None, ACTOR, state.asset, render_definition(source_graph(), opts), opts)
    # Raw copy limit stays 16MiB. Narrow SRT renderer consumer is still 1MiB;
    # ordinary 150-cue inputs are accepted; oversized consumers fail explicitly.
    for count, size in ((150, 200), (100, 12000)):
        srt = '\n\n'.join(f'cue {i}\n00:00:00,125 --> 00:00:01,750\n' + 'x' * size for i in range(count)) + '\n'
        identity = ('e' if count == 150 else 'f') * 32
        state.copies.save(OWNER, id=identity, filename='bounded.srt', title='synthetic budget', srt=srt)
        opts = selection()
        opts['saved_subtitle'] = {'copy_id': identity, 'srt_sha256': hashlib.sha256(srt.encode()).hexdigest()}
        effective = render_definition(source_graph(), opts)
        if count == 150:
            assert resolver.resolve(None, ACTOR, state.asset, effective, opts)['bindings']['transcript']['segments'] == 150
        else:
            with pytest.raises(ValueError, match='KiB'):
                resolver.resolve(None, ACTOR, state.asset, effective, opts)


def test_real_http_models_session_csrf_origin_and_preview_no_writes(state, connected, monkeypatch):
    """Real ASGI routes/middleware; account lookup and PG boundaries are doubles."""
    import ast
    import hmac
    import re
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from video_service.admission_policy import AdmissionPolicy
    from test_subtitle_copies import call
    runtime, graph, parent = connected
    ns = mount_actual_input_handlers(runtime)
    app = FastAPI()
    ns.update(app=app, Request=Request, HTTPException=HTTPException, JSONResponse=JSONResponse,
              accounts=SimpleNamespace(session=lambda cookie: {'user': {'id': ACTOR, 'role': 'user'}, 'csrf_token': 'csrf'} if cookie == 'valid' else None),
              cookie='test_session', hmac=hmac, re=re, origins={'https://unit.invalid'}, content_store=state.store, policy=AdmissionPolicy(), Depends=Depends)
    core = ast.parse((ROOT / 'packages/shared/video_service/postgres/__init__.py').read_text(encoding='utf8'))
    conflict = next(n for n in core.body if isinstance(n, ast.ClassDef) and n.name == 'Conflict')
    exec(compile(ast.Module(body=[conflict], type_ignores=[]), 'real-conflict-type-only', 'exec'), ns)
    tree = ast.parse((ROOT / 'apps/api/app/renewal.py').read_text(encoding='utf8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in {'session', 'request_boundary', 'JsonBodyLimit', 'conflict', 'invalid'}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'real-renewal-boundary', 'exec'), ns)
    def owner(value=Depends(ns['session'])):
        return value['user']['id']
    def administrator():
        raise HTTPException(403)
    ns.update(owner_dependency=Depends(owner), administrator=administrator)
    tree = ast.parse((ROOT / 'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    inspect_model = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Inspect')
    mount = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mount_runtime')
    handlers = [n for n in mount.body if isinstance(n, ast.FunctionDef) and n.name in {'inspect', 'selection_plan', 'preview', 'create'}]
    exec(compile(ast.Module(body=[inspect_model, *handlers], type_ignores=[]), 'real-renewal-render-routes', 'exec'), ns)
    app.add_middleware(ns['JsonBodyLimit'], uploads=True)
    args = dict(asset_id='d' * 32, definition_id=parent['workflow_id'], definition_revision=1, options=selection())
    monkeypatch.setattr(state.store, 'put', lambda *a, **k: pytest.fail('HTTP preview/inspect wrote CAS'))
    assert call(app, 'POST', '/api/work-entry/preview', args, cookie='absent')[0] == 401
    assert call(app, 'POST', '/api/work-entry/preview', args, csrf='bad')[0] == 403
    assert call(app, 'POST', '/api/work-entry/preview', args, origin='https://other.invalid')[0] == 403
    status, inspected = call(app, 'POST', '/api/work-entry/inspect', {k: args[k] for k in ('definition_id', 'definition_revision', 'options')})
    assert status == 200 and inspected['supported']
    assert [n['type'] for n in inspected['agent_definition']['nodes']] == ['subtitle_video_agent']
    status, planned = call(app, 'POST', '/api/work-entry/preview', args)
    assert status == 200 and planned['selected_inputs'][0]['copy_id'] == COPY
    assert call(app, 'POST', '/api/work-entry/create', {**args, 'asset_id': 'e' * 32,
        'request_id': 'synthetic-http-stale', 'token': planned['token']})[0] == 409
    assert call(app, 'POST', '/api/work-entry/preview', {**args, 'actor': OWNER})[0] == 422
    bad = deepcopy(args)
    bad['options']['saved_subtitle']['source_owner_id'] = OWNER
    assert call(app, 'POST', '/api/work-entry/preview', bad)[0] == 422
    bad['options']['saved_subtitle'] = {'copy_id': 'e' * 32, 'srt_sha256': SHA}
    status, failure = call(app, 'POST', '/api/work-entry/preview', bad)
    assert status == 422 and '찾을 수 없습니다' in failure['detail'] and 'token' not in failure
    assert not runtime.database.children and not runtime.database.outbox


@pytest.fixture
def planning(state, connected):
    """Real Create -> real _plan/_checked_input, temporary CAS, fake SQL only.

    Account/registry/engine availability remain the connected fixture's doubles.
    The review query returns synthetic rows; no PG package/session/schema exists.
    """
    import ast
    from types import MethodType
    runtime, graph, parent = connected
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id='d' * 32, definition_id=parent['workflow_id'], definition_revision=1, options=selection())
    preview = handlers['preview'](handlers['Selection'](**args), ACTOR)
    child = handlers['create'](handlers['Create'](**args, token=preview['token'], request_id='synthetic-first-plan'), ACTOR)
    child['revision'] = 1  # The real DB supplies this existing default.
    tree = ast.parse((ROOT / 'apps/orchestrator/mideagent_orchestrator/execution.py').read_text(encoding='utf8'))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Execution')
    methods = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in {'_plan', '_checked_input'}]
    ns = dict(runtime.create.__func__.__globals__)
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'real-execution-plan-methods', 'exec'), ns)
    for method in methods:
        setattr(runtime, method.name, MethodType(ns[method.name], runtime))
    execute = runtime.database.execute
    reviews = []
    def sql(query, params):
        if query.startswith('SELECT id,revision,status,confirmed_sha256 FROM review_tasks'):
            assert params[0] == ACTOR and runtime.database.jobs[params[1]]['owner_id'] == ACTOR
            return SimpleNamespace(fetchall=lambda: deepcopy(reviews))
        return execute(query, params)
    runtime.database.execute = sql
    return SimpleNamespace(runtime=runtime, child=child, reviews=reviews)


def test_first_start_plan_accepts_real_created_saved_render_bindings(planning):
    from video_service.canonical import digest
    state = planning
    before = deepcopy(state.child)
    assert state.child['snapshot']['definition']['inputs'] == {'video': 'video', 'transcript': 'transcript'}
    assert [n['type'] for n in state.child['snapshot']['definition']['nodes']] == ['generate_subtitle', 'encode', 'validate_video']
    plan = state.runtime._plan(state.runtime.database, state.child)
    assert plan['ready'], plan['reasons']
    assert plan['reasons'] == [] and plan['paid_roles'] == []
    assert state.child == before and state.child['active_claim_id'] is None
    assert len(state.runtime.database.children) == 1 and not state.runtime.database.outbox
    assert state.runtime.database.runs[state.child['id']] == []
    assert plan['snapshot_sha256'] == digest(state.child['snapshot'])


@pytest.mark.parametrize('change', ['missing_transcript', 'wrong_reference_type', 'unsupported_declared_port',
                                  'wrong_declared_type', 'missing_policy', 'unknown_policy',
                                  'custodian_pin_mismatch', 'content_pin_mismatch'])
def test_first_start_plan_refuses_unbound_wrong_type_or_unsupported_inputs(planning, change):
    from video_service.canonical import digest
    runtime, child = planning.runtime, planning.child
    snapshot = child['snapshot']
    if change == 'missing_transcript':
        del snapshot['inputs']['transcript']
    elif change == 'wrong_reference_type':
        snapshot['inputs']['transcript']['type'] = 'audio'
    elif change == 'unsupported_declared_port':
        snapshot['definition']['inputs']['other'] = 'video'
        snapshot['agent_definition']['inputs']['other'] = 'video'
        snapshot['inputs']['other'] = deepcopy(snapshot['inputs']['video'])
    elif change == 'wrong_declared_type':
        snapshot['definition']['inputs']['transcript'] = 'audio'
        snapshot['agent_definition']['inputs']['transcript'] = 'audio'
    elif change == 'missing_policy':
        del snapshot['agent_execution_policy']
    elif change == 'unknown_policy':
        snapshot['agent_execution_policy'] = 2
    elif change == 'custodian_pin_mismatch':
        ref = snapshot['inputs']['transcript']
        raw = runtime.store.read(ACTOR, ref)
        # Even identical bytes in another namespace must not replace the frozen
        # selected copy's real custodian. This writes only the temporary test CAS.
        snapshot['inputs']['transcript'] = runtime.store.put(ACTOR, [raw], 'transcript')
    elif change == 'content_pin_mismatch':
        snapshot['normal_input_bindings']['transcript']['content_sha256'] = '0' * 64
    child['snapshot_sha256'] = digest(snapshot)
    plan = runtime._plan(runtime.database, child)
    assert not plan['ready'] and plan['reasons']
    assert any('입력' in reason for reason in plan['reasons'])
    assert not runtime.database.outbox and runtime.database.runs[child['id']] == []


@pytest.mark.parametrize('port', ['video', 'transcript'])
def test_first_start_plan_preserves_legacy_single_input_with_extra_lineage(planning, port):
    from video_service.canonical import digest
    child = planning.child
    snapshot = child['snapshot']
    # Historical native contracts had no agent policy/public definition. They
    # may retain the video's reference for lineage with transcript-only inputs.
    snapshot.pop('agent_execution_policy')
    snapshot.pop('agent_definition')
    snapshot['definition']['inputs'] = {port: port}
    child['snapshot_sha256'] = digest(snapshot)
    plan = planning.runtime._plan(planning.runtime.database, child)
    assert plan['ready'] and plan['reasons'] == []
    assert set(snapshot['inputs']) == {'video', 'transcript'}


@pytest.mark.parametrize('change', ['wrong_custodian', 'wrong_bytes', 'malformed_origin'])
def test_first_start_plan_keeps_real_checked_input_content_and_custody_fences(state, planning, monkeypatch, change):
    from video_service.canonical import digest
    runtime, child = planning.runtime, planning.child
    reference = child['snapshot']['inputs']['transcript']
    if change == 'wrong_custodian':
        reference['source_owner_id'] = 'e' * 32
    elif change == 'wrong_bytes':
        reference['bytes'] += 1
    elif change == 'malformed_origin':
        reference['source_owner_id'] = '../not-an-actor'
    child['snapshot_sha256'] = digest(child['snapshot'])
    monkeypatch.setattr(state.store, 'put', lambda *a, **k: pytest.fail('plan may not materialize or repair inputs'))
    with pytest.raises(ValueError):
        runtime._plan(runtime.database, child)
    assert not runtime.database.outbox and runtime.database.runs[child['id']] == []


@pytest.mark.parametrize('guard', ['processing_review', 'recovery', 'status', 'cancel', 'review', 'availability', 'fleet'])
def test_first_start_plan_keeps_existing_admission_guards(planning, guard):
    runtime, child = planning.runtime, planning.child
    if guard == 'processing_review': runtime.review_block = True
    if guard == 'recovery': child['recovery_ready'] = False
    if guard == 'status': child['status'] = 'running'
    if guard == 'cancel': child['cancel_requested'] = True
    if guard == 'review': planning.reviews.append({'id': 'e' * 32, 'revision': 1, 'status': 'draft', 'confirmed_sha256': None})
    if guard == 'availability': runtime._execution_reasons = lambda *a: ['synthetic registry/budget unavailable']
    if guard == 'fleet':
        def unavailable(db, roles):
            assert roles == ['generate_subtitle', 'encode', 'validate_video']
            return ['synthetic CPU unavailable']
        runtime.fleet = SimpleNamespace(reasons=unavailable)
    plan = runtime._plan(runtime.database, child)
    assert not plan['ready'] and plan['reasons']
    assert not runtime.database.outbox and runtime.database.runs[child['id']] == []


def test_first_start_plan_keeps_token_binding_and_preflight_context(state, planning):
    from video_service.canonical import digest
    from video_service.cpu_input_policy import LARGE_PROFILE
    runtime, child = planning.runtime, planning.child
    before = runtime._plan(runtime.database, child)
    assert runtime._plan(runtime.database, deepcopy(child)) == before  # reopened frozen input
    child['snapshot']['normal_input_bindings']['transcript']['language'] = 'ja'
    child['snapshot_sha256'] = digest(child['snapshot'])
    after = runtime._plan(runtime.database, child)
    assert after['ready'] and before['token'] != after['token']
    child['revision'] += 1
    assert runtime._plan(runtime.database, child)['token'] != after['token']
    # Exercise the existing _checked_input fence with an explicit synthetic
    # preflight receipt and the existing policy object, not an actual CPU run.
    child['snapshot']['cpu_input_policy'] = deepcopy(LARGE_PROFILE)
    child['snapshot_sha256'] = digest(child['snapshot'])
    verified = {'snapshot_sha256': child['snapshot_sha256'],
                'references': {digest(ref) for ref in child['snapshot']['inputs'].values()}}
    with pytest.raises(ValueError, match='context changed'):
        runtime._plan(runtime.database, child, {**verified, 'snapshot_sha256': '0' * 64})
    with pytest.raises(ValueError, match='context changed'):
        runtime._plan(runtime.database, child, {**verified, 'references': set()})
    assert runtime._plan(runtime.database, child, verified)['ready']


@pytest.mark.parametrize('explicit_video', [False, True])
def test_first_start_plan_accepts_existing_inline_agent_input_contract(planning, explicit_video):
    from mideagent_orchestrator.workflow import render_definition
    runtime = planning.runtime
    graph = render_definition(source_graph(), selection())
    graph['revision'] = 1
    if explicit_video:
        graph['inputs']['video'] = 'video'
    runtime._job_definition = lambda *a: (OWNER, deepcopy(graph))
    runtime.job_definition = lambda *a: deepcopy(graph)
    handlers = mount_actual_input_handlers(runtime)
    args = dict(asset_id='d' * 32, definition_id='f' * 32, definition_revision=1,
                options={'subtitle_srt': '007\n00:00:00,125 --> 00:00:01,750\nexisting inline\n', 'input_language': 'en'})
    preview = handlers['preview'](handlers['Selection'](**args), ACTOR)
    child = handlers['create'](handlers['Create'](**args, token=preview['token'], request_id='synthetic-inline-plan'), ACTOR)
    child['revision'] = 1
    assert child['snapshot']['normal_input_bindings']['transcript']['kind'] == 'subtitle_srt'
    assert 'source_owner_id' not in child['snapshot']['inputs']['transcript']
    plan = runtime._plan(runtime.database, child)
    assert plan['ready'], plan['reasons']
    assert not runtime.database.outbox and runtime.database.runs[child['id']] == []
