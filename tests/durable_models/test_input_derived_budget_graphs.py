"""Input-derived caps exercised by the real local role graphs (no providers)."""
import json

import pytest

from graph_execution import translation_case, speech_case, private_content_store
from video_service.model_call_budget import resolve


def resolved(store, role, raw, width):
    owner = 'd' * 32
    port, kind, batch = ('audio', 'transcription', 'bounded_60s_v1') if role == 'transcribe' else ('transcript', 'translation', 'bounded_100x16k_v1')
    reference = store.put(owner, [raw], port)
    command = {'agent': {'id': role}, 'options': {'max_model_calls': 'auto'}, 'inputs': {port: reference},
               kind: {'candidates': [{} for _ in range(width)], 'batch_policy': batch}}
    return resolve(store, owner, command, policy_version=2)['max_model_calls']


def test_automatic_empty_translation_has_zero_budget_and_zero_calls(tmp_path):
    Agent, task, source = translation_case(tmp_path, [])
    task['max_calls'] = resolved(private_content_store(tmp_path), 'translate', source.read_bytes(), 2)
    assert task['max_calls'] == 0
    agent = Agent(tmp_path / 'state', lambda *_: pytest.fail('empty input must not call'))
    result = agent.run(task, source)
    assert result['status'] == 'completed' and result['model_calls'] == 0
    assert agent.run(task, source) == result


def test_actual_translation_batches_can_each_use_configured_fallback(tmp_path):
    rows = [{'start': i, 'end': i + 1, 'text': 'source'} for i in range(201)]
    Agent, task, source = translation_case(tmp_path, rows)
    task['max_calls'] = resolved(private_content_store(tmp_path), 'translate', source.read_bytes(), 2)
    assert task['max_calls'] == 6
    calls = []
    def tool(task, batch, candidate):
        calls.append((batch.chunk_index, candidate))
        if candidate == 0:
            return {'status': 'failed', 'error': 'rate_limited'}
        return {'status': 'received', 'reply': json.dumps(['translated'] * len(batch.segments))}
    agent = Agent(tmp_path / 'state', tool)
    result = agent.run(task, source)
    assert result['status'] == 'completed' and result['model_calls'] == 6
    assert calls == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
    assert agent.run(task, source) == result and len(calls) == 6


@pytest.mark.parametrize('error,expected_calls,status', [('unavailable', 2, 'completed'), ('timeout', 1, 'held')])
def test_asr_derived_candidate_allowance_does_not_retry_unknown(tmp_path, error, expected_calls, status):
    from mideagent_model_tools.endpoints import EndpointFailure
    Agent, task, source = speech_case(tmp_path)
    task['chunk_frames'] = 960000
    task['max_calls'] = resolved(private_content_store(tmp_path), 'transcribe', source.read_bytes(), 2)
    calls = []
    def tool(model, *_):
        calls.append(model)
        if model == task['models'][0]:
            raise EndpointFailure('offline fixture', code=error)
        return []
    agent = Agent(tmp_path / 'state', tool)
    result = agent.run(task, source)
    assert result['status'] == status and result['model_calls'] == expected_calls
    assert agent.run(task, source) == result and len(calls) == expected_calls
