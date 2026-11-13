"""Offline budgets over real immutable CAS bytes, never provider requests."""
import io
from pathlib import Path
import wave

import pytest

from video_service.canonical import canonical, digest
from video_service.content_store import ContentStore
from video_service.editor_contracts import resolve_editor_contracts

OWNER = 'a' * 32


@pytest.mark.parametrize('role', ['transcribe', 'translate'])
def test_new_default_is_auto_and_old_numeric_snapshot_is_unchanged(role):
    source = {'nodes': [{'type': role, 'options': {}}]}
    assert resolve_editor_contracts(source)['nodes'][0]['options']['max_model_calls'] == 'auto'
    assert source['nodes'][0]['options'] == {}
    for cap in ('1', '128'):
        frozen = {'nodes': [{'type': role, 'options': {'max_model_calls': cap}}]}
        before = canonical(frozen)
        assert resolve_editor_contracts(frozen)['nodes'][0]['options']['max_model_calls'] == cap
        assert canonical(frozen) == before


def command(store, role, raw, candidates=2, cap='auto'):
    port = 'audio' if role == 'transcribe' else 'transcript'
    ref = store.put(OWNER, [raw], port, max_bytes=1024**3)
    return {'agent': {'id': role}, 'options': {'max_model_calls': cap},
            'inputs': {port: ref},
            ('transcription' if role == 'transcribe' else 'translation'): {
                'candidates': [{'model_id': str(i)} for i in range(candidates)],
                'batch_policy': 'bounded_60s_v1' if role == 'transcribe' else 'bounded_100x16k_v1'}}


def wav(frames):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        block = b'\0' * (960000 * 2)
        while frames:
            count = min(frames, 960000)
            out.writeframesraw(block[:count * 2]); frames -= count
    return stream.getvalue()


def test_asr_actual_129_chunks_and_fallback_expand_but_numeric_cap_does_not(tmp_path):
    from video_service.model_call_budget import resolve
    store = ContentStore(tmp_path)
    request = command(store, 'transcribe', wav(128 * 960000 + 1))
    before = digest(request)
    result = resolve(store, OWNER, request, policy_version=2)
    assert result['max_model_calls'] == 258
    assert result['model_call_plan']['planned_units'] == 129
    assert result['model_call_plan']['candidate_count'] == 2
    assert result['model_call_plan']['inputs_sha256'] == digest(request['inputs'])
    assert digest(request) == before
    for cap in ('1', '128'):
        request['options']['max_model_calls'] = cap
        assert resolve(store, OWNER, request, policy_version=2) == {'max_model_calls': int(cap)}


@pytest.mark.parametrize('rows,expected', [(201, 3), (0, 0)])
def test_translation_uses_actual_splitter_and_candidates(tmp_path, rows, expected):
    from video_service.model_call_budget import resolve
    store = ContentStore(tmp_path)
    source = [{'start': i, 'end': i + 1, 'text': 'hello'} for i in range(rows)]
    request = command(store, 'translate', canonical(source), candidates=4)
    result = resolve(store, OWNER, request, policy_version=2)
    assert result['max_model_calls'] == expected * 4
    assert result['model_call_plan']['planned_units'] == expected


def test_translation_byte_bound_is_not_row_count_estimate(tmp_path):
    from video_service.model_call_budget import resolve
    store = ContentStore(tmp_path)
    source = [{'start': i, 'end': i + 1, 'text': 'x' * 9000} for i in range(3)]
    request = command(store, 'translate', canonical(source))
    assert resolve(store, OWNER, request, policy_version=2)['max_model_calls'] == 6


def test_auto_refuses_bad_input_and_candidate_width(tmp_path):
    from video_service.model_call_budget import resolve
    store = ContentStore(tmp_path)
    request = command(store, 'transcribe', wav(16000)[:-2])
    with pytest.raises(ValueError):
        resolve(store, OWNER, request, policy_version=2)
    request = command(store, 'translate', b'[]', candidates=5)
    with pytest.raises(ValueError):
        resolve(store, OWNER, request, policy_version=2)


def test_templates_and_catalog_expose_auto_only_for_asr_mt():
    from video_service.node_contracts import NODES
    nodes = {n['id']: n for n in NODES}
    for role in ('transcribe', 'translate'):
        assert nodes[role]['options']['max_model_calls'][0] == 'auto'
        assert '128' in nodes[role]['options']['max_model_calls']
    assert 'auto' not in nodes['vocalize']['options']['max_model_calls']
    templates = (Path(__file__).resolve().parents[2] / 'apps/web/src/workflow-templates.ts').read_text()
    assert "max_model_calls: '128'" not in templates
    assert "max_model_calls: 'auto'" in templates


@pytest.mark.parametrize('cancelled', [False, True])
def test_auto_empty_legacy_translation_never_calls(tmp_path, cancelled):
    from types import SimpleNamespace
    from video_service.model_call_budget import resolve
    from video_service.postgres.translation import TranslationRuntime
    store = ContentStore(tmp_path)
    request = command(store, 'translate', b'[]')
    request['translation'].update(resolve(store, OWNER, request, policy_version=2))
    ledger = SimpleNamespace(command=request, max_calls=0, call_count=lambda: 0)
    def no_call(*a, **kw):
        pytest.fail('zero planned work cannot invoke any provider or persistence')
    runtime = SimpleNamespace(translate=no_call)
    result = TranslationRuntime.translate_batched(
        runtime, request['translation']['candidates'], [], source_language='en', target_language='ko',
        cancelled=lambda: cancelled, record=no_call, persist=no_call, load=no_call, ledger=ledger, max_calls=0,
    )
    assert result['status'] == ('cancelled' if cancelled else 'completed')
    assert result['call_count'] == 0 and result['selected'] is None


def test_actual_byte_batches_above_old_4096_bound_remain_finite(tmp_path):
    from video_service.model_call_budget import resolve, frozen_cap, verify
    from video_service.cpu_input_policy import model_runtime_seconds
    store = ContentStore(tmp_path)
    source = [{'start': i, 'end': i + 1, 'text': 'x' * 9000} for i in range(1025)]
    request = command(store, 'translate', canonical(source), candidates=4)
    result = resolve(store, OWNER, request, policy_version=2)
    request['translation'].update(result)
    assert frozen_cap(request) == verify(store, OWNER, request, policy_version=2) == 4100
    assert result['model_call_plan']['planned_units'] == 1025
    assert model_runtime_seconds(4100, input_derived=True) == 7200
    with pytest.raises(ValueError):
        model_runtime_seconds(4100)
    # Arithmetic alone is insufficient: enrollment checks the actual CAS planner.
    request['translation']['model_call_plan']['planned_units'] += 1
    request['translation']['max_model_calls'] += 4
    with pytest.raises(ValueError, match='input_plan_changed'):
        verify(store, OWNER, request, policy_version=2)


@pytest.mark.parametrize('rows', [0, 1025])
def test_legacy_ledger_freezes_exact_derived_integer_and_plan_columns(tmp_path, rows):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from video_service.model_call_budget import resolve
    from video_service.postgres.model_batches import ModelBatchLedger
    store = ContentStore(tmp_path)
    source = [{'start': i, 'end': i + 1, 'text': 'x' * 9000} for i in range(rows)]
    request = command(store, 'translate', canonical(source), candidates=4)
    request.update(run_id='b' * 32, attempt_id='c' * 32, generation=1)
    request['translation'].update(resolve(store, OWNER, request, policy_version=2))
    calls = []
    class Database:
        def connection(self):
            return nullcontext(self)
        def execute(self, sql, params):
            calls.append((sql, params))
            if sql.startswith('SELECT j.cancel_requested'):
                value = dict(cancel_requested=False, generation=1, job_generation=1, active_claim_id='claim',
                             claim_id='claim', status='running', live=True, request_sha256=digest(request))
            elif sql.startswith('SELECT snapshot'):
                value = {'snapshot': {'inputs': request['inputs']}}
            elif sql.startswith('INSERT INTO model_call_budgets'):
                assert 'planned_units,candidate_count' in sql
                assert params[-3:] == (rows * 4, rows, 4)
                value = None
            elif sql.startswith('SELECT command_sha256,max_calls'):
                value = {'command_sha256': digest(request), 'max_calls': rows * 4}
            else:
                pytest.fail(sql)
            return SimpleNamespace(fetchone=lambda: value)
    ledger = ModelBatchLedger(Database(), OWNER, request, max_calls=rows * 4)
    assert ledger.max_calls == rows * 4
    assert ledger.command_sha == digest(request)
    assert len(calls) == 4
