"""Real preview/create/command/enrollment code with existing offline SQL fixtures."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_audio_original_input import audio_runtime, store, create_audio, OWNER, ACTOR
from test_saved_subtitle_translation import mt, state, connected, recovery_runtime, source_execution, args
from video_service.canonical import canonical, digest

ROOT = Path(__file__).resolve().parents[2]


def assert_bridge_budget_binding(task):
    from mideagent_model_tools.client import RoleToolBridge
    from video_service.role_policy import tool_context
    packet = {'task_id': task['task_id'], **tool_context(task)}
    if task['role'] == 'transcription':
        packet['candidate_index'] = 0
    RoleToolBridge._packet_context(packet, task, {'task_id'})
    changed = {**task, 'max_calls': task['max_calls'] + 1}
    with pytest.raises(ValueError, match='outside_grant'):
        RoleToolBridge._packet_context(packet, changed, {'task_id'})


def roles_for(runtime):
    from video_service.packed_projection import validate_projection_clock
    path = ROOT / 'packages/shared/video_service/postgres/model_roles.py'
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModelRoles')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
               {'_policy_version', '_current', 'enroll', '_model_binding', '_translation_envelope'}]
    ns = dict(__package__='video_service.postgres', deepcopy=deepcopy, json=json, digest=digest,
              Jsonb=lambda x: deepcopy(x), Conflict=ValueError, validate_projection_clock=validate_projection_clock)
    shell = ast.ClassDef(name='ModelRoles', bases=[], keywords=[], body=methods, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[shell], type_ignores=[])), str(path), 'exec'), ns)
    roles = ns['ModelRoles'](); roles.runtime = runtime
    return roles


@pytest.mark.parametrize('audio_runtime', [{'max_calls': 'auto'}, {'max_calls': 1}, {'max_calls': 128}], indirect=True)
def test_actual_audio_preview_claim_freeze_enroll_and_snapshot_preservation(audio_runtime, tmp_path):
    from mideagent_media_tools.operations import run
    from video_service.long_audio_budget import validate_command
    from video_service.role_task_contracts import validate
    from video_service.role_policy import tool_context
    state = audio_runtime
    runtime = state.runtime
    child = create_audio(state)
    original_snapshot = canonical(child['snapshot'])
    child.update(status='waiting', active_claim_id='6' * 32)
    state.grant['allowed'] = True
    preparation = runtime.claim_next(ACTOR, child['id'])
    output = tmp_path / 'normalized'; output.mkdir()
    result = run(preparation, runtime.store.owner_root(ACTOR), output)
    assert result['status'] == 'completed'
    refs = {p: runtime.store.put(ACTOR, [(output / r['storage_key']).read_bytes()], r['type'], max_bytes=1024**3)
            for p, r in result['outputs'].items()}
    runtime.database.runs[child['id']][0].update(status='completed', result={'status': 'completed', 'outputs': refs})
    command = runtime.claim_next(ACTOR, child['id'])
    cap = command['options']['max_model_calls']
    expected = 2 if cap == 'auto' else int(cap)
    assert command['transcription']['max_model_calls'] == expected
    assert validate_command(command)['max_model_calls'] == expected
    if cap == 'auto':
        assert command['transcription']['model_call_plan']['planned_units'] == 1
    else:
        assert 'model_call_plan' not in command['transcription']
    frozen = canonical(command)
    role = roles_for(runtime)
    envelope = role.enroll(ACTOR, command)
    validate(envelope, 'result', expected_role='transcription')
    assert envelope['task']['max_calls'] == expected
    assert_bridge_budget_binding(envelope['task'])
    assert tool_context(envelope['task'])['task_sha256'] == digest(envelope['task'])
    assert canonical(command) == frozen
    assert canonical(child['snapshot']) == original_snapshot


@pytest.mark.parametrize('cap', ['auto', '1', '128'])
def test_actual_translation_preview_token_command_and_envelope(mt, monkeypatch, cap):
    from types import ModuleType
    import sys
    from video_service.translation_languages import languages
    from video_service.long_audio_budget import validate_command
    from video_service.role_task_contracts import validate
    from video_service.role_policy import tool_context
    mt.definition['nodes'][1]['tool_settings']['translate']['max_model_calls'] = cap
    before = canonical(mt.definition)
    request = args(mt)
    preview = mt.handlers['preview'](mt.handlers['Selection'](**request), ACTOR)
    budget = preview['model_call_budgets'][0]
    assert budget['max_calls'] == (None if cap == 'auto' else int(cap))
    assert budget['minimum_audio_calls'] is None
    assert budget['budget_mode'] == ('input_derived' if cap == 'auto' else 'explicit')
    assert not mt.runtime.database.children
    child = mt.handlers['create'](mt.handlers['Create'](**request, token=preview['token'], request_id='auto-budget-test', paid_confirmed=True), ACTOR)
    snapshot = canonical(child['snapshot'])
    assert digest(child['snapshot']['definition']) == preview['execution_definition_sha256']
    node = child['snapshot']['definition']['nodes'][0]
    _, command = mt.runtime._insert_run(mt.runtime.database, child, node, child['snapshot']['inputs'], 'running')
    expected = 2 if cap == 'auto' else int(cap)
    assert command['translation']['max_model_calls'] == expected
    assert validate_command(command)['max_model_calls'] == expected
    translation = ModuleType('video_service.postgres.translation')
    translation.languages = languages
    translation.segments = lambda *a: pytest.fail('bounded translation must use the real batch planner')
    monkeypatch.setitem(sys.modules, translation.__name__, translation)
    frozen = canonical(command)
    envelope, _ = roles_for(mt.runtime)._translation_envelope(ACTOR, command)
    validate(envelope, 'result', expected_role='translation')
    assert envelope['task']['max_calls'] == expected
    assert_bridge_budget_binding(envelope['task'])
    assert tool_context(envelope['task'])['task_sha256'] == digest(envelope['task'])
    assert canonical(command) == frozen and canonical(child['snapshot']) == snapshot
    assert canonical(mt.definition) == before
    if cap == 'auto':
        changed = deepcopy(command)
        changed['translation']['max_model_calls'] += 1
        with pytest.raises(ValueError):
            roles_for(mt.runtime)._translation_envelope(ACTOR, changed)
