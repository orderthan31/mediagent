"""Synthetic ordinary-SRT correction specimens; no services or provider calls."""
from copy import deepcopy
from pathlib import Path
import sys
from html import escape

import pytest
from test_normal_inputs import (ROOT, ROWS, SRT, accepted_inputs, inline_runtime,
                               input_graph, mount_actual_input_handlers, connect_accepted_runtime,
                               tmp_path, source_execution, recovery_runtime)


def ordinary_srt(count=150, text=None):
    return "\n\n".join(f"{i:04}\n00:{i // 60:02}:{i % 60:02},125 --> 00:{i // 60:02}:{i % 60:02},875\n{text or ('ordinary subtitle ' * 14)}" for i in range(count)) + "\n"


def test_ordinary_srt_over_100_cues_and_20kb_uses_actual_preview_create(inline_runtime):
    runtime, parent, graph, writes = inline_runtime
    handlers = mount_actual_input_handlers(runtime)
    text = ordinary_srt()
    assert len(text.encode()) > 20000
    selection = handlers['Selection'](asset_id=parent['asset_id'], definition_id=parent['workflow_id'], definition_revision=1,
                                      options={'subtitle_srt': text, 'input_language': 'ja'})
    plan = handlers['preview'](selection, parent['owner_id'])
    assert plan['selected_inputs'][0]['segments'] == 150 and not writes
    child = handlers['create'](handlers['Create'](**selection.model_dump(), token=plan['token'], request_id='ordinary-srt'), parent['owner_id'])
    assert child['snapshot']['definition']['nodes'][0]['options']['cue_policy'] == 'preserve_v1'
    assert child['snapshot']['normal_input_bindings']['transcript']['segments'] == 150
    assert not runtime.database.outbox


def test_accepted_ordinary_transcript_over_batch_size_is_usable(accepted_inputs, inline_runtime):
    from video_service.canonical import canonical
    state = accepted_inputs
    runtime, parent, graph, writes = inline_runtime
    rows = [{'id': str(i), 'start': i, 'end': i + .5, 'text': 'accepted text ' * 20} for i in range(101)]
    ref = state.runtime.store.put(state.job['owner_id'], [canonical(rows)], 'transcript')
    state.runs[1]['result']['outputs']['transcript'] = ref
    connect_accepted_runtime(runtime, parent, graph, state)
    result = runtime.normal_input_plan(state.actor, state.asset['asset_id'], graph, {'accepted_inputs': {'transcript': {'job_id': state.job['id'], 'run_id': state.runs[1]['id'], 'port': 'transcript'}}})
    assert result['segments'] == rows and not writes
    from video_service.canonical import digest
    child = runtime.create(state.actor, state.asset['asset_id'], parent['workflow_id'], 1,
                           request_id='ordinary-accepted', options={'accepted_inputs': {'transcript': {'job_id': state.job['id'], 'run_id': state.runs[1]['id'], 'port': 'transcript'}}},
                           input_plan_sha256=digest(result['bindings']))
    assert child['snapshot']['normal_input_bindings']['transcript']['segments'] == 101
    assert not writes and not runtime.database.outbox


@pytest.mark.parametrize('kind', ['subtitle_file_agent', 'subtitle_video_agent'])
def test_selected_input_mode_propagates_through_translation_but_default_is_unchanged(kind):
    from mideagent_orchestrator.workflow import compile_definition, default_definition
    plan = compile_definition(input_graph(kind, translated=True), input_language='ja')
    generate = next(n for n in plan['definition']['nodes'] if n['type'] == 'generate_subtitle')
    assert generate['options']['cue_policy'] == 'preserve_v1'
    old = compile_definition(default_definition())
    assert all('cue_policy' not in n['options'] for n in old['definition']['nodes'])


def test_selected_cue_mode_does_not_leak_into_an_independent_asr_branch():
    from mideagent_orchestrator.workflow import compile_definition
    graph = input_graph()
    asr = input_graph('transcription_agent', audio=True)['nodes'][0]
    asr.update(id='asr', options={})
    exported = deepcopy(graph['nodes'][0]); exported['id'] = 'asr_export'
    graph['nodes'] += [asr, exported]
    graph['edges'] = [{'id': 'asr_flow', 'source': {'node': 'asr', 'port': 'media'}, 'target': {'node': 'asr_export', 'port': 'media'}}]
    tools = {n['id']: n for n in compile_definition(graph)['definition']['nodes']}
    assert tools['goal__generate_subtitle']['options']['cue_policy'] == 'preserve_v1'
    assert 'cue_policy' not in tools['asr_export__generate_subtitle']['options']


@pytest.mark.parametrize('revision,format', [('1', 'srt'), ('3', 'srt_smi'), ('5', 'srt_smi')])
def test_actual_executor_preserves_long_cue_literal_ids_times_and_text(tmp_path, revision, format):
    sys.path.insert(0, str(ROOT / 'tools/media'))
    from mideagent_media_tools.operations import run
    from video_service.canonical import canonical, digest
    from video_service.agent_protocol import schemas
    from video_service.rabbitmq_transport import validate_command
    from video_service.long_audio_budget import role_budget
    input_root = tmp_path / 'inputs'; input_root.mkdir()
    output_root = tmp_path / 'outputs'; output_root.mkdir()
    text = '  a long cue with  spaces ' * 16 + '\nsecond line  '
    rows = [{'id': '007', 'start': .25, 'end': 8.125, 'text': text}]
    rows += [{'id': f'{i:04}', 'start': 10 + i, 'end': 10.5 + i, 'text': 'next'} for i in range(101)]
    raw = canonical(rows); sha = digest(rows)
    (input_root / 'blobs').mkdir()
    file = input_root / 'blobs' / sha; file.write_bytes(raw)
    command = {'protocol_version': 1, 'run_id': 'b' * 32, 'attempt_id': 'c' * 32, 'generation': 1,
               'agent': {'id': 'generate_subtitle', 'revision': revision},
               'inputs': {'transcript': {'storage_key': 'blobs/' + sha, 'sha256': sha, 'bytes': len(raw), 'type': 'transcript'}},
               'options': {'format': format, 'language': 'ja', 'cue_policy': 'preserve_v1'}}
    if revision == '5':
        command['options']['media_budget'] = 'audio_long_v5'; command['resource_budget'] = role_budget('generate_subtitle')
    wire = deepcopy(command); wire['inputs']['transcript']['storage_key'] = 'blobs/' + sha
    branches = schemas()['agent.command.v1.schema.json']['properties']['command']['oneOf']
    assert any('preserve_v1' in b['properties']['options']['properties'].get('cue_policy', {}).get('enum', []) for b in branches)
    import json
    for name in ('agent.command.v1.schema.json', 'agent.result.v1.schema.json'):
        stored = json.loads((ROOT / 'packages/shared/video_service/contracts' / name).read_text(encoding='utf-8'))
        stored_branches = stored['properties']['command']['oneOf']
        assert [b['properties']['options']['properties']['cue_policy'] for b in stored_branches if b['properties']['agent']['properties']['id']['const'] == 'generate_subtitle'] == [{'enum': ['reflow_v1', 'preserve_v1']}] * 2
    validate_command(wire)
    result = run(command, input_root, output_root)
    assert result['status'] == 'completed', result
    srt = (output_root / result['outputs']['subtitles']['storage_key']).read_bytes()
    expected = f'007\n00:00:00,250 --> 00:00:08,125\n{text}\n\n'.encode()
    assert srt.startswith(expected) and srt.count(b' --> ') == 102
    if format == 'srt_smi':
        sami = (output_root / result['outputs']['sami']['storage_key']).read_bytes()
        assert ('<SYNC Start="250"><P Class="SUBTTL">' + escape(text).replace('\n', '<BR>') + '</P></SYNC>').encode() in sami
        assert b'Start="8125"' in sami and b'Start="10000"' in sami


def test_selected_native_input_budgets_are_checked_before_any_cas_write(inline_runtime):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    runtime, parent, graph, writes = inline_runtime
    rows = [{'id': str(i), 'start': i, 'end': i + .5, 'text': 'a' * 6000} for i in range(200)]
    resolver = NormalInputs(runtime)
    with pytest.raises(ValueError, match='1024KiB'):
        resolver.resolve(None, parent['owner_id'], {}, graph, {'transcript': rows})
    graph['nodes'][0]['options']['format'] = 'srt_smi'
    result = resolver.resolve(None, parent['owner_id'], {}, graph, {'transcript': rows})
    assert len(result['segments']) == 200 and not writes
    # Pure export is not restricted by the per-row translation wire budget.
    rows = [{'id': '1', 'start': 0, 'end': 1, 'text': 'a' * 16000}]
    assert resolver.resolve(None, parent['owner_id'], {}, graph, {'transcript': rows})['segments'] == rows
    with pytest.raises(ValueError, match='16KB'):
        resolver.resolve(None, parent['owner_id'], {}, input_graph(translated=True), {'transcript': rows})


def test_finite_output_budget_is_checked_before_creation(inline_runtime):
    from mideagent_orchestrator.normal_inputs import NormalInputs
    runtime, parent, graph, writes = inline_runtime
    graph['nodes'][0]['tool_settings'] = {'generate_subtitle': {'format': 'srt_smi', 'media_budget': 'audio_long_v5'}}
    # Input <16MiB; HTML escaping would exceed the selected v5 16MiB output.
    rows = [{'id': str(i), 'start': i, 'end': i + .5, 'text': '<' * 15000} for i in range(300)]
    with pytest.raises(ValueError, match='출력 파일'):
        NormalInputs(runtime).resolve(None, parent['owner_id'], {}, graph, {'transcript': rows})
    assert not writes and not runtime.database.outbox and not runtime.database.children


def test_legacy_cue_generation_still_uses_its_exact_old_reflow(tmp_path):
    sys.path.insert(0, str(ROOT / 'tools/media'))
    from mideagent_media_tools.operations import run
    from video_service.canonical import canonical, digest
    rows = [{'id': '007', 'start': 0, 'end': 10, 'text': 'a' * 100}]
    raw = canonical(rows); sha = digest(rows)
    inputs = tmp_path / 'input'; (inputs / 'blobs').mkdir(parents=True)
    (inputs / 'blobs' / sha).write_bytes(raw)
    outputs = tmp_path / 'output'; outputs.mkdir()
    command = {'protocol_version': 1, 'run_id': 'b' * 32, 'attempt_id': 'c' * 32, 'generation': 1,
               'agent': {'id': 'generate_subtitle', 'revision': '1'},
               'inputs': {'transcript': {'storage_key': 'blobs/' + sha, 'sha256': sha, 'bytes': len(raw), 'type': 'transcript'}}, 'options': {'format': 'srt'}}
    result = run(command, inputs, outputs)
    assert result['status'] == 'completed'
    expected = f"1\n00:00:00,000 --> 00:00:08,400\n{'a' * 42}\n{'a' * 42}\n\n2\n00:00:08,400 --> 00:00:10,000\n{'a' * 16}\n"
    assert (outputs / result['outputs']['subtitles']['storage_key']).read_text(encoding='utf-8') == expected


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('external', [False, True])
def test_actual_translation_envelope_normalizes_custodian_without_changing_command(version, external, monkeypatch):
    import ast
    import json
    from types import ModuleType, SimpleNamespace
    from video_service.canonical import canonical, digest
    from video_service.role_policy import model_binding
    from video_service.translation_languages import languages
    from video_service.transcript_input import parse_segments
    from video_service.role_task_contracts import validate
    translation_path = ROOT / 'packages/shared/video_service/postgres/translation.py'
    segment_ast = next(n for n in ast.parse(translation_path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'segments')
    namespace = {'canonical': canonical, 'parse_segments': parse_segments}
    exec(compile(ast.Module(body=[segment_ast], type_ignores=[]), str(translation_path), 'exec'), namespace)
    module = ModuleType('video_service.postgres.translation')
    module.languages, module.segments = languages, namespace['segments']
    monkeypatch.setitem(sys.modules, module.__name__, module)
    path = ROOT / 'packages/shared/video_service/postgres/model_roles.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == 'ModelRoles')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_translation_envelope')
    namespace = {'__package__': 'video_service.postgres', 'json': json, 'Conflict': ValueError}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    rows = [{'id': '007', 'start': 0, 'end': 1, 'text': 'synthetic'}]
    owner, custodian = 'a' * 32, 'b' * 32
    ref = {'type': 'transcript', 'bytes': len(canonical(rows)), 'sha256': digest(rows), 'storage_key': 'blobs/' + digest(rows), **({'source_owner_id': custodian} if external else {})}
    reads = []
    def read(*args, **kwargs):
        reads.append(args); return canonical(rows)
    runtime = SimpleNamespace(store=SimpleNamespace(read=read))
    roles = SimpleNamespace(runtime=runtime, _policy_version=lambda *_: version, _model_binding=model_binding)
    pin = {'model_id': 'd' * 32, 'revision': 7, 'unit': 'exact pin'}
    command = {'attempt_id': 'c' * 32, 'agent': {'id': 'translate'}, 'inputs': {'transcript': ref},
               'translation': {'candidates': [pin], 'source_language': 'ja', 'target_language': 'pt-BR'}}
    before = deepcopy(command)
    envelope, pins = namespace['_translation_envelope'](roles, owner, command)
    validate(envelope, 'result', expected_role='translation')
    assert envelope['source'] == {'owner': custodian if external else owner, 'reference': {k: v for k, v in ref.items() if k != 'source_owner_id'}}
    assert envelope['output_owner'] == owner and pins == [pin]
    assert command == before and reads == [(owner, ref)]


def test_actual_json_body_limit_changes_only_exact_input_routes():
    import ast
    import asyncio
    import re
    from fastapi.responses import JSONResponse
    path = ROOT / 'apps/api/app/renewal.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == 'JsonBodyLimit')
    namespace = {'re': re, 'JSONResponse': JSONResponse}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    async def request(route):
        accepted, sent = [], []
        async def app(scope, receive, send):
            accepted.append(await receive())
        async def receive():
            return {'type': 'http.request', 'body': b'x' * 200000, 'more_body': False}
        async def send(message):
            sent.append(message)
        await namespace['JsonBodyLimit'](app)({'type': 'http', 'method': 'POST', 'path': route}, receive, send)
        return accepted, sent
    for route in ('/api/work-entry/preview', '/api/work-entry/create', '/api/settings/work-entry/preview', '/api/settings/work-entry/create'):
        accepted, sent = asyncio.run(request(route))
        assert accepted and not sent
    for route in ('/api/auth/login', '/api/work-entry/create/extra', '/api/jobs'):
        accepted, sent = asyncio.run(request(route))
        assert not accepted and sent[0]['status'] == 413


def test_recovery_of_pre_correction_selected_input_keeps_absent_cue_policy(inline_runtime):
    from video_service.canonical import digest
    runtime, original, graph, writes = inline_runtime
    first = runtime.create(original['owner_id'], original['asset_id'], original['workflow_id'], 1,
                           request_id='pre-correction-input', options={'subtitle_srt': SRT, 'input_language': 'ja'})
    parent = runtime.database.jobs[first['id']]
    parent['status'] = 'failed'
    parent['snapshot']['definition']['nodes'][0]['options'].pop('cue_policy')
    parent['snapshot_sha256'] = digest(parent['snapshot'])
    before = deepcopy(parent['snapshot'])
    writes.clear()
    child = runtime.create(original['owner_id'], original['asset_id'], original['workflow_id'], 1,
                           request_id='preserve-old-cues', parent_id=parent['id'], options=deepcopy(before['options']))
    assert child['snapshot'] == {**before, 'recovery': {'parent_id': parent['id'], 'snapshot_sha256': parent['snapshot_sha256']}}
    assert not writes and not runtime.database.outbox
