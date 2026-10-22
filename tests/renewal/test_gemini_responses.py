"""Response-only Gemini regression fixtures; no network, DB or provider call."""
import httpx
from video_service.postgres.translation import TranslationRuntime

ORIGIN = 'http://127.0.0.1:9419'
SOURCE = [{'start': 0, 'end': 1, 'text': 'Synthetic input'}]


def run_response(response, *, fallback=True):
    pins = [{
        'owner_id': 'a' * 32, 'model_id': char * 32, 'revision': 1,
        'sha256': char * 64, 'connection_id': char * 32, 'connection_revision': 2,
        'remote_model': name, 'endpoint': ORIGIN + '/v1beta' if protocol == 'gemini' else ORIGIN + '/v1',
        'protocol': protocol, 'credential_ref': 'db:' + char * 32,
        'model_types': ['text'], 'input_modalities': ['text'],
        'output_modalities': ['text'], 'capabilities': ['text_generation'],
    } for char, name, protocol in [('b', 'fixture-gemini', 'gemini'), ('c', 'fixture-fallback', 'openai_compatible')]]
    calls = []
    journal = []

    class FixtureCredentials:
        def model(self, owner, model_id, revision):
            return next(p for p in pins if p['owner_id'] == owner and p['model_id'] == model_id and p['revision'] == revision)

        def resolve(self, owner, connection_id, reference):
            return 'synthetic-fixture-header-key'

    def wire(request):
        calls.append(str(request.url))
        if ':generateContent' in request.url.path:
            return httpx.Response(200, json=response)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '["fallback should not run on refusal"]'}}]})

    runtime = TranslationRuntime(FixtureCredentials(), transport_factory=lambda: httpx.MockTransport(wire), approved_origins={ORIGIN}, mode='controlled_http')
    result = runtime.translate(pins if fallback else pins[:1], SOURCE, source_language='en', target_language='ko', cancelled=lambda: False, record=journal.append)
    return result, calls, journal


def test_explicit_prompt_block_stops_before_candidate_lookup_without_fallback():
    result, calls, journal = run_response({'promptFeedback': {'blockReason': 'SAFETY'}})
    assert result['status'] == 'failed'
    assert len(calls) == 1, 'Explicit prompt refusal must not call the fallback'
    assert result['attempts'][0]['error'] == 'request_rejected'
    assert result['attempts'][0]['transition'] == 'stop'
    assert result['selected'] is None and result['segments'] is None
    assert journal[-1][0]['error'] == 'request_rejected'


def stop_response(parts):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': parts}}]}


def test_signed_final_text_allows_metadata_without_adopting_signature():
    result, calls, _ = run_response(stop_response([{
        'text': '["합성 번역"]', 'thought': False,
        'thoughtSignature': 'c3ludGhldGljLXNpZw==',
        'partMetadata': {'source': 'metadata is not translated text'},
    }]))
    assert result['status'] == 'completed'
    assert result['segments'] == [{**SOURCE[0], 'text': '합성 번역'}]
    assert result['selected']['protocol'] == 'gemini'
    assert len(calls) == 1
    assert 'c3ludGhldGljLXNpZw==' not in str(result)


def test_thought_signature_tool_and_media_parts_never_become_translation():
    parts = [
        {'text': '["private thought must not be adopted"]', 'thought': True},
        {'thoughtSignature': 'c2lnbmF0dXJlLW9ubHk='},
        {'functionCall': {'name': 'fixture', 'args': {'text': 'not translation'}}},
        {'inlineData': {'mimeType': 'text/plain', 'data': 'bm90IHRyYW5zbGF0aW9u'}},
        {'fileData': {'mimeType': 'text/plain', 'fileUri': 'fixture://not-fetched'}},
        {'toolCall': {'name': 'fixture'}},
        {'toolResponse': {'response': {'text': 'not translation'}}},
        {'executableCode': {'language': 'PYTHON', 'code': 'not executed'}},
        {'codeExecutionResult': {'output': 'not translation'}},
        {'text': '["ambiguous media text"]', 'inlineData': {'mimeType': 'text/plain', 'data': 'bm8='}},
        {'text': '["합성 최종문"]', 'thoughtSignature': 'c3ludGhldGljLXNpZw=='},
    ]
    result, calls, _ = run_response(stop_response(parts))
    assert result['status'] == 'completed'
    assert result['segments'] == [{**SOURCE[0], 'text': '합성 최종문'}]
    assert len(calls) == 1
    assert 'private thought' not in str(result)


def test_thought_only_without_final_text_remains_invalid():
    result, calls, _ = run_response(stop_response([{'text': '["private thought"]', 'thought': True}, {'thoughtSignature': 'c2ln'}]), fallback=False)
    assert result['status'] == 'failed'
    assert result['attempts'][0]['error'] == 'invalid_response'
    assert result['segments'] is None and result['selected'] is None
    assert len(calls) == 1


def test_signed_final_text_with_invalid_subtitle_shape_stays_invalid():
    result, calls, _ = run_response(stop_response([{'text': '{"not":"subtitle array"}', 'thoughtSignature': 'c2ln'}]), fallback=False)
    assert result['status'] == 'failed'
    assert result['attempts'][0]['error'] == 'invalid_response'
    assert result['segments'] is None and len(calls) == 1
