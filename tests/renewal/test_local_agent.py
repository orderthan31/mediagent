"""CPU-only contract checks with generated transcript bytes, never user media."""
import hashlib
import json

import pytest

from video_service.agent_runtime import AgentCancelled, AgentInputError, catalog, run


@pytest.fixture
def local_request(tmp_path):
    source, output = tmp_path / 'input', tmp_path / 'output'
    source.mkdir()
    output.mkdir()
    raw = json.dumps([{'start': 0, 'end': 1.5, 'text': 'Synthetic subtitle.'}]).encode()
    (source / 'transcript.json').write_bytes(raw)
    request = {
        'protocol_version': 1, 'run_id': 'local-run', 'attempt_id': 'attempt-1',
        'generation': 1, 'agent': {'id': 'generate_subtitle', 'revision': '1'},
        'inputs': {'transcript': {'storage_key': 'transcript.json', 'type': 'transcript',
                   'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}},
        'options': {'line_width': 42, 'max_lines': 2},
    }
    return request, source, output


def test_cpu_subtitle_receipt_and_duplicate_attempt(local_request):
    request, source, output = local_request
    events = []
    result = run(request, source, output, emit=events.append)
    assert result['status'] == 'completed'
    ref = result['outputs']['subtitles']
    raw = (output / ref['storage_key']).read_bytes()
    assert b'00:00:00,000 --> 00:00:01,500' in raw
    assert b'Synthetic subtitle.' in raw
    assert ref['sha256'] == hashlib.sha256(raw).hexdigest() and ref['bytes'] == len(raw)
    assert json.loads((output / 'local-run-attempt-1/receipt.json').read_bytes()) == result
    assert [event['status'] for event in events] == ['running', 'completed']
    with pytest.raises(FileExistsError):
        run(request, source, output)
    assert catalog()['agents'][0]['runtime'] == {'device': 'cpu', 'network': False, 'provider_calls': False}


def test_artifact_tamper_and_traversal_are_rejected(local_request):
    request, source, output = local_request
    request['inputs']['transcript']['sha256'] = '0' * 64
    with pytest.raises(AgentInputError):
        run(request, source, output)
    request['inputs']['transcript']['storage_key'] = '../transcript.json'
    with pytest.raises(AgentInputError):
        run(request, source, output)
    assert list(output.iterdir()) == []


def test_cooperative_cancel_persists_no_completed_output(local_request):
    request, source, output = local_request
    checks = []
    def check():
        checks.append(True)
        if len(checks) == 2:
            raise AgentCancelled()
    result = run(request, source, output, check=check)
    assert result['status'] == 'cancelled' and result['outputs'] == {}
    assert not (output / 'local-run-attempt-1/subtitles.srt').exists()


def test_mutated_request_cannot_publish_success(local_request):
    request, source, output = local_request
    def emit(event):
        request['generation'] += 1
    result = run(request, source, output, emit=emit)
    assert result['status'] == 'failed' and result['error']['code'] == 'invalid_input'
    assert result['outputs'] == {}
    assert not (output / 'local-run-attempt-1/subtitles.srt').exists()
