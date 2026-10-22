"""Registered API transcription, not real recognition-accuracy acceptance."""
import io
import wave

from video_service import model_profile


def pcm_audio():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 8000)
    return output.getvalue()


def test_only_timed_audio_contract_models_are_advertised():
    supports = getattr(model_profile, 'supports_transcription', None)
    assert supports is not None, 'Explicit timed-audio model compatibility missing'
    profile = {'model_types': ['speech_recognition'], 'input_modalities': ['audio'], 'output_modalities': ['text'], 'capabilities': ['speech_recognition']}
    assert supports(profile, 'gemini', 'gemini-fixture')
    assert supports(profile, 'openai', 'whisper-1')
    assert supports(profile, 'openai_compatible', 'whisper-1')
    assert not supports(profile, 'openai', 'gpt-4o-transcribe')
    assert not supports(profile, 'anthropic', 'fixture')
    assert not supports({'model_types': ['text'], 'input_modalities': ['text'], 'output_modalities': ['text'], 'capabilities': ['text_generation']}, 'gemini', 'gemini-fixture')


def test_native_audio_wires_return_provider_timestamps_without_inventing_them():
    import base64
    import json

    import httpx
    import video_service.model_endpoints as endpoints

    for name, model in [('GeminiAudioAdapter', 'gemini-fixture'), ('OpenAIAudioAdapter', 'whisper-1')]:
        adapter_type = getattr(endpoints, name, None)
        assert adapter_type is not None, name + ' missing'
        audio, calls = pcm_audio(), []

        def wire(request, name=name, calls=calls, audio=audio):
            calls.append(request)
            if name == 'GeminiAudioAdapter':
                assert request.url.path.endswith('/models/gemini-fixture:generateContent')
                assert request.headers['x-goog-api-key'] == 'synthetic-audio-key'
                body = json.loads(request.content)
                data = body['contents'][0]['parts'][0]['inlineData']
                assert data['mimeType'] == 'audio/wav'
                assert base64.b64decode(data['data']) == audio
                return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '[{"start":0.1,"end":0.4,"text":"Synthetic speech"}]', 'thoughtSignature': 'c2ln'}]}}]})
            assert request.url.path.endswith('/audio/transcriptions')
            assert request.headers['authorization'] == 'Bearer synthetic-audio-key'
            assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
            body = request.content
            assert audio in body and b'whisper-1' in body and b'verbose_json' in body
            assert b'timestamp_granularities[]' in body and b'segment' in body
            assert b'name="language"' in body and b'en' in body
            return httpx.Response(200, json={'text': 'Synthetic speech', 'segments': [{'start': 0.1, 'end': 0.4, 'text': 'Synthetic speech'}]})

        adapter = adapter_type('http://127.0.0.1:9419/v1', transport=httpx.MockTransport(wire), approved_origins={'http://127.0.0.1:9419'}, api_key='synthetic-audio-key')
        try:
            assert adapter.transcribe(model, audio, 'en') == [{'start': 0.1, 'end': 0.4, 'text': 'Synthetic speech'}]
        finally:
            adapter.close()
        assert len(calls) == 1


def test_registered_transcription_reuses_finite_fallback_and_refuses_missing_timing():
    import importlib.util
    assert importlib.util.find_spec('video_service.postgres.transcription') is not None, 'Registered ASR runtime missing'
    import httpx
    from video_service.postgres.transcription import TranscriptionRuntime

    profile = {'owner_id': 'a' * 32, 'revision': 1, 'sha256': 'a' * 64, 'connection_revision': 2, 'credential_ref': None, 'model_types': ['speech_recognition'], 'input_modalities': ['audio'], 'output_modalities': ['text'], 'capabilities': ['speech_recognition']}
    pins = [{**profile, 'model_id': char * 32, 'connection_id': char * 32, 'endpoint': 'http://127.0.0.1:9419/' + path, 'protocol': protocol, 'remote_model': model, 'credential_ref': 'db:' + char * 32} for char,path,protocol,model in [('b','fail/v1beta','gemini','gemini-fixture'),('c','ok/v1','openai','whisper-1')]]
    calls = []

    class Credentials:
        def model(self, owner, model_id, revision):
            return next(p for p in pins if p['model_id'] == model_id)
        def resolve(self, *args):
            return 'synthetic-audio-key'

    def wire(request):
        calls.append(request.url.path)
        if '/fail/' in request.url.path:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={'segments': [{'start': 0.1, 'end': 0.4, 'text': 'Synthetic speech'}]})

    runtime = TranscriptionRuntime(Credentials(), transport_factory=lambda: httpx.MockTransport(wire), approved_origins={'http://127.0.0.1:9419'}, mode='controlled_http')
    result = runtime.transcribe(pins, pcm_audio(), source_language='en', cancelled=lambda: False, record=lambda _: None)
    assert result['status'] == 'completed'
    assert [a['status'] for a in result['attempts']] == ['failed', 'completed']
    assert result['segments'] == [{'start': 0.1, 'end': 0.4, 'text': 'Synthetic speech'}]
    assert len(calls) == 2
    runtime.transport_factory = lambda: httpx.MockTransport(lambda _: httpx.Response(200, json={'text': 'No time information'}))
    rejected = runtime.transcribe(pins[1:], pcm_audio(), source_language='en', cancelled=lambda: False, record=lambda _: None)
    assert rejected['status'] == 'failed' and rejected['segments'] is None


def test_unsupported_audio_is_a_failed_receipt_before_any_provider_attempt():
    from types import SimpleNamespace

    from video_service.postgres.translation import execute_translation

    class Store:
        def read(self, *args, **kwargs):
            raise ValueError('Structured content size exceeded')

    runtime = SimpleNamespace(store=Store(), transcription_runtime=SimpleNamespace(mode='controlled_http'))
    command = {'protocol_version': 1, 'run_id': 'a' * 32, 'attempt_id': 'b' * 32, 'generation': 1,
               'agent': {'id': 'transcribe', 'revision': '1'}, 'inputs': {'audio': {}, 'timeline': {}},
               'transcription': {'candidates': [], 'source_language': 'en', 'paid_authorized': False}}
    result = execute_translation(runtime, 'c' * 32, command)
    assert result['status'] == 'failed' and result['outputs'] == {}
    assert result['transcription']['attempts'] == []
    assert result['transcription']['input_error'] == 'unsupported_audio_or_timeline'
