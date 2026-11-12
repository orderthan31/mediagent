"""MT-only saved-copy connection. Synthetic registry/DB, temporary CAS, no services."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import MethodType, ModuleType, SimpleNamespace

import pytest
from test_saved_subtitle_render import state, connected, OWNER, ACTOR, source_graph
from test_goal_corrections import source_execution
from test_goal_recovery_policy import recovery_runtime
from test_normal_inputs import mount_actual_input_handlers

ROOT = Path(__file__).resolve().parents[2]
COPY = '9' * 32
CUSTODIAN = '8' * 32
PRIMARY = {'model_id': '1' * 32, 'revision': 7}
FALLBACK = {'model_id': '2' * 32, 'revision': 8}
SRT = '  \n00:00:00,125 --> 00:00:00,750\n literal text \nsecond line\n\n' + '1234567890' * 15 + '\n00:00:01,000 --> 00:00:02,800\nnext\n'
SHA = hashlib.sha256(SRT.encode()).hexdigest()
LLM = '{"reasoning_effort":"high","max_tokens":1024,"temperature":0.2}'


def options(**overrides):
    return {'saved_subtitle': {'copy_id': COPY, 'srt_sha256': SHA}, 'input_language': 'ja',
            'translation_goal': {'node_id': 'translation', 'options': {'target_language': 'pt-BR', **overrides}}}


def graph():
    value = source_graph()
    value['revision'] = 1
    node = value['nodes'][1]
    node.update(model_ref=deepcopy(PRIMARY), fallback_refs=[deepcopy(FALLBACK)])
    node['options']['llm_options'] = LLM
    node['tool_settings'] = {'translate': {'max_model_calls': '4', 'batch_policy': 'bounded_100x16k_v1', 'media_budget': 'audio_long_v5'}}
    return value


@pytest.fixture
def mt(state, connected, monkeypatch):
    runtime, _, parent = connected
    definition = graph()
    state.copies.save(CUSTODIAN, id=COPY, filename='saved actual.smi', title='MT fixture copy', srt=SRT)
    runtime.job_definition = lambda *a: deepcopy(definition)
    runtime._job_definition = lambda *a: (OWNER, deepcopy(definition))
    rows = {ref['model_id']: {**ref, 'name': 'Synthetic registered ' + str(i), 'remote_model': 'synthetic-model-' + str(i),
            'connection_id': '3' * 32, 'connection_revision': 5, 'sha256': str(i + 4) * 64,
            'endpoint': 'https://unit.invalid', 'protocol': 'openai_compatible', 'provider': 'openai_compatible',
            'credential_ref': 'unit-credential-reference', 'model_active': True, 'connection_active': True,
            'model_types': ['text'], 'input_modalities': ['text'], 'output_modalities': ['text'],
            'capabilities': ['text_generation', 'structured_output']} for i, ref in enumerate((PRIMARY, FALLBACK))}
    execute = runtime.database.execute
    def sql(query, params):
        if query.startswith('SELECT mr.*'):
            assert params[0] == OWNER, 'binding must use server-derived workflow owner'
            row = rows.get(params[1])
            return SimpleNamespace(fetchone=lambda: deepcopy(row) if row and row['revision'] == params[2] else None)
        if query.startswith('SELECT name FROM model_revisions'):
            assert params[0] == OWNER
            return SimpleNamespace(fetchone=lambda: {'name': rows[params[1]]['name']})
        if query.startswith('SELECT id,revision,status,confirmed_sha256 FROM review_tasks'):
            return SimpleNamespace(fetchall=lambda: [])
        return execute(query, params)
    runtime.database.execute = sql
    namespace = dict(runtime.create.__func__.__globals__)
    namespace.update(resource_id=lambda value: value, Missing=LookupError)
    for filename, cls_name, names in (
        ('apps/orchestrator/mideagent_orchestrator/execution.py', 'Execution', {'_plan', '_checked_input', '_preflight_cpu_inputs', '_execution_reasons', '_engine_role'}),
        ('packages/shared/video_service/postgres/intake.py', 'Intake', {'_bindings'}),
    ):
        tree = ast.parse((ROOT / filename).read_text(encoding='utf8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
        for original in cls.body:
            if isinstance(original, ast.FunctionDef) and original.name in names:
                node = deepcopy(original); node.decorator_list = []
                module_ns = {**namespace, **({'__package__': 'video_service.postgres'} if cls_name == 'Intake' else {})}
                exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), module_ns)
                method = module_ns[node.name]
                setattr(runtime, node.name, method if node.name == '_engine_role' else MethodType(method, runtime))
    engine = ModuleType('video_service.postgres.engine_runtimes')
    engine.EngineRuntimes = SimpleNamespace(resolve_in=lambda *a, **k: pytest.fail('no engine/native probe'))
    monkeypatch.setitem(sys.modules, engine.__name__, engine)
    available = {'value': True}
    runtime.translation_runtime = SimpleNamespace(mode='synthetic_metadata', available=lambda pin: available['value'],
        requires_paid=lambda pins: True, credentials=SimpleNamespace(model=lambda *a: pytest.fail('do not reinterpret workflow model in actor namespace')))
    return SimpleNamespace(runtime=runtime, definition=definition, parent=parent, rows=rows, available=available,
                           handlers=mount_actual_input_handlers(runtime), store=state.store, copies=state.copies)


def args(mt, opts=None):
    return dict(asset_id='d' * 32, definition_id=mt.parent['workflow_id'], definition_revision=1, options=opts or options())


def test_explicit_mt_selection_preserves_goal_model_budget_and_old_render():
    from mideagent_orchestrator.workflow import selected_definition, render_definition, compile_definition
    source = graph(); before = deepcopy(source)
    opts = options(); opts['translation_goal']['model_ref'] = FALLBACK
    effective = selected_definition(source, opts)
    assert source == before
    assert [n['type'] for n in effective['nodes']] == ['translation_agent']
    assert effective['nodes'][0]['model_ref'] == FALLBACK
    assert effective['nodes'][0]['fallback_refs'] == [PRIMARY]
    native = compile_definition(effective, input_language='ja')['definition']
    assert [n['type'] for n in native['nodes']] == ['translate']
    assert native['nodes'][0]['options']['max_model_calls'] == '4'
    assert native['nodes'][0]['options']['llm_options'] == LLM
    assert compile_definition(effective)['outputs'] == {'translation': {'transcript': {'node': 'translation__translate', 'port': 'transcript'}}}
    old = {'saved_subtitle': options()['saved_subtitle'], 'render_goal': {'node_id': 'subtitle_video', 'options': {}}}
    assert selected_definition(source, old) == render_definition(source, old)
    assert selected_definition(source, {}) == source


@pytest.mark.parametrize('selected', [None, FALLBACK])
def test_actual_preview_create_plan_and_first_command_are_mt_only_and_owner_bound(mt, monkeypatch, selected):
    from video_service.canonical import digest, canonical
    from video_service.content_store import reference_origin
    request = args(mt)
    if selected:
        request['options']['translation_goal']['model_ref'] = selected
    put = mt.store.put
    monkeypatch.setattr(mt.store, 'put', lambda *a, **k: pytest.fail('read-only preparation wrote CAS'))
    inspection = mt.runtime.inspect(ACTOR, request['definition_id'], 1, options=request['options'])
    assert inspection['supported'] and inspection['paid_roles'] == ['translation']
    assert 'credential_ref' not in repr(inspection) and 'endpoint' not in repr(inspection)
    plan = mt.handlers['preview'](mt.handlers['Selection'](**request), ACTOR)
    assert plan['paid_roles'] == ['translation'] and plan['model_call_budgets'][0]['max_calls'] == 4
    assert not mt.runtime.database.children and not mt.runtime.database.outbox
    monkeypatch.setattr(mt.store, 'put', put)
    create = mt.handlers['Create'](**request, token=plan['token'], request_id='synthetic-mt-only', paid_confirmed=True)
    child = mt.handlers['create'](create, ACTOR); child['revision'] = 1
    snapshot = child['snapshot']
    assert child['status'] == 'draft' and child['active_claim_id'] is None and child['parent_id'] is None
    assert snapshot['translation_selection'] == {'version': 1, 'node_id': 'translation', 'source_definition_sha256': digest(mt.definition)}
    assert snapshot['source_definition_sha256'] == digest(mt.definition)
    assert digest(snapshot['definition']) == plan['execution_definition_sha256']
    assert 'render_selection' not in snapshot
    assert [n['type'] for n in snapshot['definition']['nodes']] == ['translate']
    assert snapshot['normal_input_bindings']['transcript']['custodian_id'] == CUSTODIAN
    assert snapshot['agent_input_contexts']['translation__translate']['transcript'] == {'node': '$input', 'port': 'transcript', 'language': 'ja'}
    owner, ref = reference_origin(ACTOR, snapshot['inputs']['transcript'])
    rows = __import__('json').loads(mt.store.read(owner, ref))
    assert owner == CUSTODIAN and rows[0]['id'] == '  ' and str(rows[1]['id']) == '1234567890' * 15
    assert rows[0]['text'] == ' literal text \nsecond line'
    verified = mt.runtime._preflight_cpu_inputs(ACTOR, child['id'])
    assert mt.runtime._plan(mt.runtime.database, child, verified)['ready']
    tool = snapshot['definition']['nodes'][0]
    _, command = mt.runtime._insert_run(mt.runtime.database, child, tool, {'transcript': snapshot['inputs']['transcript']}, 'running')
    from video_service.node_contracts import validate_node
    from video_service.long_audio_budget import validate_command
    validate_command(command)
    assert validate_node({'node': 'translate', 'inputs': {'transcript': 'transcript'}, 'options': command['options']})['valid']
    assert command['agent']['id'] == 'translate'
    assert command['translation']['source_language'] == 'ja' and command['translation']['target_language'] == 'pt-BR'
    assert command['translation']['max_model_calls'] == 4 and command['translation']['batch_policy'] == 'bounded_100x16k_v1'
    candidates = command['translation']['candidates']
    assert [p['owner_id'] for p in candidates] == [OWNER, OWNER]
    assert [p['revision'] for p in candidates] == ([8, 7] if selected else [7, 8])
    assert all(p['inference']['options']['reasoning_effort'] == 'high' for p in candidates)
    assert all(p['credential_ref'] == 'unit-credential-reference' for p in candidates)
    assert command['inputs']['transcript']['source_owner_id'] == CUSTODIAN
    assert mt.copies.get(COPY)['srt'] == SRT and not mt.runtime.database.outbox
    # Only construct/validate the existing model-role envelope. No enroll,
    # publish, provider, paid call, worker or actual first claim is performed.
    from video_service.translation_languages import languages
    from video_service.canonical import canonical
    from video_service.transcript_input import parse_segments
    translation = ModuleType('video_service.postgres.translation')
    translation.languages = languages
    tree = ast.parse((ROOT / 'packages/shared/video_service/postgres/translation.py').read_text(encoding='utf8'))
    segment_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'segments')
    segment_ns = {'canonical': canonical, 'parse_segments': parse_segments}
    exec(compile(ast.Module(body=[segment_fn], type_ignores=[]), 'actual-single-batch-validator', 'exec'), segment_ns)
    translation.segments = segment_ns['segments']
    monkeypatch.setitem(sys.modules, translation.__name__, translation)
    role_ns = {'__package__': 'video_service.postgres', 'json': __import__('json'), 'Conflict': ValueError}
    tree = ast.parse((ROOT / 'packages/shared/video_service/postgres/model_roles.py').read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModelRoles')
    role = SimpleNamespace(runtime=mt.runtime)
    for original in cls.body:
        if isinstance(original, ast.FunctionDef) and original.name in {'_translation_envelope', '_policy_version', '_model_binding'}:
            fn = deepcopy(original); fn.decorator_list = []
            exec(compile(ast.Module(body=[fn], type_ignores=[]), 'actual-model-role-envelope', 'exec'), role_ns)
            method = role_ns[fn.name]
            setattr(role, fn.name, method if fn.name == '_model_binding' else MethodType(method, role))
    envelope, frozen = role._translation_envelope(ACTOR, command)
    from video_service.role_task_contracts import validate
    validate(envelope, 'result', expected_role='translation')
    assert envelope['source']['owner'] == CUSTODIAN and envelope['output_owner'] == ACTOR
    assert envelope['task']['max_calls'] == 4 and envelope['task']['source_language'] == 'ja'
    assert 'source_owner_id' not in envelope['source']['reference']
    assert frozen == candidates


@pytest.mark.parametrize('change', ['foreign_model', 'wrong_goal', 'mixed_goal', 'actor_key', 'wrong_sha', 'missing_copy', 'missing_model'])
def test_bad_mt_selection_never_prepares_or_creates(mt, change):
    opts = options()
    if change == 'foreign_model': opts['translation_goal']['model_ref'] = {'model_id': 'f' * 32, 'revision': 1}
    if change == 'wrong_goal': opts['translation_goal']['node_id'] = 'subtitle_video'
    if change == 'mixed_goal': opts['render_goal'] = {'node_id': 'subtitle_video', 'options': {}}
    if change == 'actor_key': opts['translation_goal']['owner_id'] = ACTOR
    if change == 'wrong_sha': opts['saved_subtitle']['srt_sha256'] = '0' * 64
    if change == 'missing_copy': opts['saved_subtitle']['copy_id'] = 'e' * 32
    if change == 'missing_model': mt.definition['nodes'][1].pop('model_ref')
    with pytest.raises((ValueError, LookupError)):
        mt.handlers['preview'](mt.handlers['Selection'](**args(mt, opts)), ACTOR)
    assert not mt.runtime.database.children and not mt.runtime.database.outbox


@pytest.mark.parametrize('change', ['video', 'copy', 'source_language', 'target_language', 'model', 'llm_options', 'source_revision'])
def test_actual_create_rejects_stale_mt_preview_without_materializing(mt, monkeypatch, change):
    request = args(mt)
    plan = mt.handlers['preview'](mt.handlers['Selection'](**request), ACTOR)
    if change == 'video': request['asset_id'] = 'e' * 32
    if change == 'copy':
        mt.copies.save(CUSTODIAN, id='7' * 32, filename='other.srt', title='another immutable copy', srt=SRT)
        request['options']['saved_subtitle']['copy_id'] = '7' * 32
    if change == 'source_language': request['options']['input_language'] = 'en'
    if change == 'target_language': request['options']['translation_goal']['options']['target_language'] = 'pl'
    if change == 'model': request['options']['translation_goal']['model_ref'] = FALLBACK
    if change == 'llm_options': request['options']['translation_goal']['options']['llm_options'] = '{"max_tokens":512}'
    if change == 'source_revision': mt.definition['name'] = 'different source revision context'
    monkeypatch.setattr(mt.store, 'put', lambda *a, **k: pytest.fail('stale preparation may not materialize'))
    with pytest.raises(ValueError, match='변경'):
        mt.handlers['create'](mt.handlers['Create'](**request, token=plan['token'], request_id='stale-mt', paid_confirmed=True), ACTOR)
    assert not mt.runtime.database.children and not mt.runtime.database.outbox


def test_mt_paid_consent_availability_and_e13_plan_guards_remain(mt, monkeypatch):
    from fastapi import HTTPException
    from video_service.canonical import digest
    request = args(mt)
    plan = mt.handlers['preview'](mt.handlers['Selection'](**request), ACTOR)
    with pytest.raises(HTTPException) as denied:
        mt.handlers['create'](mt.handlers['Create'](**request, token=plan['token'], request_id='no-new-paid-consent'), ACTOR)
    assert denied.value.status_code == 403 and not mt.runtime.database.children
    child = mt.handlers['create'](mt.handlers['Create'](**request, token=plan['token'], request_id='synthetic-guard', paid_confirmed=True), ACTOR)
    child['revision'] = 1
    def first_plan():
        child['snapshot_sha256'] = digest(child['snapshot'])
        mt.runtime.database.jobs[child['id']] = deepcopy(child)
        return mt.runtime._plan(mt.runtime.database, child, mt.runtime._preflight_cpu_inputs(ACTOR, child['id']))
    assert first_plan()['ready']
    mt.available['value'] = False
    assert not first_plan()['ready']
    mt.available['value'] = True
    child['snapshot']['translation_paid_authorized'] = False
    assert not first_plan()['ready']
    child['snapshot']['translation_paid_authorized'] = True
    del child['snapshot']['inputs']['transcript']
    assert not first_plan()['ready']
    assert not mt.runtime.database.outbox and mt.runtime.database.runs[child['id']] == []


def test_original_resolved_mt_budget_and_native_input_constraints_are_preserved(mt):
    from mideagent_orchestrator.workflow import selected_definition, compile_definition
    source = graph(); source['nodes'][1].pop('tool_settings')
    original = next(n for n in compile_definition(source)['definition']['nodes'] if n['type'] == 'translate')
    selected = compile_definition(selected_definition(source, options()))['definition']['nodes'][0]
    for key in ('max_model_calls', 'batch_policy', 'media_budget'):
        assert selected['options'][key] == original['options'][key]
    bad_srt = SRT.replace('00:00:01,000', '00:00:00,500')
    mt.copies.save(CUSTODIAN, id='7' * 32, filename='overlap.srt', title='native MT rejects overlap', srt=bad_srt)
    opts = options(); opts['saved_subtitle'] = {'copy_id': '7' * 32, 'srt_sha256': hashlib.sha256(bad_srt.encode()).hexdigest()}
    with pytest.raises(ValueError, match='시각'):
        mt.handlers['preview'](mt.handlers['Selection'](**args(mt, opts)), ACTOR)
    assert not mt.runtime.database.children
