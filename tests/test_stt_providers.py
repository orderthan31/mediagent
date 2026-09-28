import asyncio
import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import wave

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'workers/media'), str(ROOT / 'packages/shared')]
from media_worker import translation_transport as transport
from media_worker.stt_transport import request_fields, parse_transcription, request_transcription
from media_worker.providers import GeminiProvider, retry_delay
from media_worker.content_block import ContentBlockedError
from media_worker.llm_diagnostics import attempt_context, new_context
from media_worker.llm_trace import capture_calls
from media_worker.transcription_queue import RetryableTranscriptionError
from video_service.llm_settings import LLMSettingsStore
from video_service.llm_providers import STT_MODELS


def audio_bytes(seconds=2):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * (16000 * seconds))
    return buffer.getvalue()


CUES = [{'start': .1, 'end': 1.5, 'text': 'Hello.'}]


class SttTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.client.__aenter__.return_value = self.client
        factory = patch.object(transport.httpx, 'AsyncClient', return_value=self.client)
        factory.start()
        self.addCleanup(factory.stop)
        flag = patch.dict(os.environ, {'PAID_LLM_ENABLED': 'true'})
        flag.start()
        self.addCleanup(flag.stop)
        self.parts = [{'inlineData': {'mimeType': 'audio/wav', 'data': base64.b64encode(audio_bytes()).decode()}}]

    async def request(self, provider='xai', model='grok-voice-transcribe-2.0', check=lambda: None):
        return await request_transcription(provider, 'test-stt-key', model, self.parts, 'ja', check, 1, retry_delay)

    async def test_protocols_send_only_selected_key_audio_and_language(self):
        for provider, model in [('xai', 'grok-voice-transcribe-2.0'), ('openai', 'whisper-1'),
                                ('openai', 'gpt-4o-transcribe-diarize'), ('openrouter', 'microsoft/mai-transcribe-2')]:
            self.client.post.return_value = httpx.Response(200, json={
                'text': 'Hello.', 'words' if provider == 'xai' else 'segments': CUES})
            self.assertEqual(await self.request(provider, model), CUES)
            args = self.client.post.call_args
            self.assertEqual(args.kwargs['headers'], {'Authorization': 'Bearer test-stt-key'})
            self.assertEqual(args.kwargs['files']['file'][1], audio_bytes())
            fields = args.kwargs['data']
            self.assertEqual(fields['language'], 'ja')
            self.assertEqual(fields['model'], model)
            self.assertNotIn('prompt', fields)
            if provider == 'xai':
                self.assertTrue(args.args[0].endswith('/v1/stt'))
                self.assertEqual(fields['format'], 'true')
            elif model.endswith('diarize'):
                self.assertEqual(fields['response_format'], 'diarized_json')
                self.assertEqual(fields['chunking_strategy'], 'auto')
            else:
                self.assertEqual(fields['timestamp_granularities[]'], 'segment')

    async def test_paid_lock_and_model_validation_prevent_requests(self):
        with patch.dict(os.environ, {'PAID_LLM_ENABLED': 'false'}):
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                await self.request()
        with self.assertRaises(ValueError):
            await self.request('openai', 'gpt-4o-transcribe')
        self.client.post.assert_not_called()

    async def test_rate_limit_and_auth_and_policy_are_distinct(self):
        self.client.post.return_value = httpx.Response(429, headers={'retry-after': '2'})
        with self.assertRaises(RetryableTranscriptionError) as caught:
            await self.request()
        self.assertTrue(caught.exception.shared_cooldown)
        self.assertEqual(caught.exception.delay, 2)
        self.client.post.return_value = httpx.Response(403, text='test-stt-key')
        with self.assertRaisesRegex(RuntimeError, 'authentication'):
            await self.request()
        self.client.post.return_value = httpx.Response(400, json={'error': {'code': 'content_filter'}})
        with self.assertRaises(ContentBlockedError) as caught:
            await self.request()
        self.assertEqual(caught.exception.provider, 'xai')

    async def test_cancellation_stops_upload(self):
        stopped = asyncio.Event()
        started = asyncio.Event()
        async def wait(*args, **kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                stopped.set()
        self.client.post.side_effect = wait
        task = asyncio.create_task(self.request())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())

    async def test_cross_provider_fallback_keeps_budget_and_language(self):
        instance = GeminiProvider({'transcription_provider': 'xai', 'transcription_model': 'grok-voice-transcribe-2.0',
            'transcription_fallback_provider': 'gemini', 'transcription_fallback_model': 'test-fallback',
            'api_keys': {'xai': 'test-stt-key'}, 'api_key': 'test-google-key', 'fallback_on_error': True})
        self.client.post.return_value = httpx.Response(429)
        context = attempt_context.set(new_context(stage='transcription', segment=0))
        self.addCleanup(attempt_context.reset, context)
        with patch.object(instance, '_request_once', AsyncMock(return_value=CUES)) as fallback:
            self.assertEqual(await instance._request(self.parts, {}, lambda: None, instance.transcription_model,
                max_attempts=1, trace_attempt=1, stt_language='ja'), CUES)
            await instance._request(self.parts, {}, lambda: None, instance.transcription_model,
                max_attempts=1, trace_attempt=2, stt_language='ja')
            self.assertEqual(self.client.post.call_count, 1)
            self.assertEqual(fallback.call_count, 2)
            self.assertEqual(fallback.call_args.args[3], 'test-fallback')


class SttContractTests(unittest.TestCase):
    def test_word_grouping_punctuation_gaps_and_original_times(self):
        words = [{'start': 0, 'end': .2, 'text': 'Hello'}, {'start': .3, 'end': .6, 'text': 'world.'},
                 {'start': 2, 'end': 2.5, 'text': 'Again'}]
        self.assertEqual(parse_transcription('xai', {'words': words}, 3), [
            {'start': 0, 'end': .6, 'text': 'Hello world.'}, {'start': 2, 'end': 2.5, 'text': 'Again'}])
        self.assertEqual(parse_transcription('xai', {'words': words}, 3, 'ja')[0]['text'], 'Helloworld.')

    def test_bad_or_missing_timestamps_never_fabricated(self):
        for data in ({'text': 'hello'}, {'text': 'hello', 'segments': []},
                     {'segments': [{'start': 2, 'end': 1, 'text': 'no'}]},
                     {'segments': [{'start': 0, 'end': 50, 'text': 'no'}]}):
            with self.assertRaises(ValueError):
                parse_transcription('openai', data, 2)
        self.assertEqual(parse_transcription('openai', {'text': '', 'segments': []}, 2), [])
        self.assertNotIn('language', request_fields('xai', 'grok-voice-transcribe-2.0', 'auto'))

    def test_settings_legacy_defaults_and_unsupported_models(self):
        root = ROOT / 'data/test-runs' / uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        store = LLMSettingsStore(root)
        values = store.public()
        self.assertEqual(values['transcription_provider'], 'gemini')
        payload = {key: value for key, value in values.items() if key not in ('credentials', 'has_api_key', 'key_source')}
        for provider, model in [('anthropic', 'claude-test'), ('xai', 'grok-chat'), ('openai', 'gpt-4o-transcribe')]:
            with self.assertRaises(ValueError):
                store.update(None, {**payload, 'transcription_provider': provider, 'transcription_model': model})
        result = store.update(None, {**payload, 'transcription_provider': 'xai',
            'transcription_model': 'grok-voice-transcribe-2.0', 'transcription_fallback_provider': 'openai',
            'transcription_fallback_model': 'whisper-1'})
        self.assertEqual(result['transcription_provider'], 'xai')

    def test_preflight_selected_keys_and_cache_identity(self):
        instance = GeminiProvider({'api_key': '', 'transcription_provider': 'xai',
            'transcription_model': 'grok-voice-transcribe-2.0', 'api_keys': {'xai': 'test-key'}})
        instance.validate_for_stages(['transcribe'])
        self.assertEqual(instance.transcription_identity, 'xai:grok-voice-transcribe-2.0')
        instance.preferences.update(fallback_on_error=True, transcription_fallback_provider='openai',
                                    transcription_fallback_model='whisper-1')
        with self.assertRaisesRegex(RuntimeError, 'openai'):
            instance.validate_for_stages(['transcribe'])
        self.assertEqual(GeminiProvider({'transcription_model': 'legacy'}).transcription_identity, 'legacy')

    def test_packed_windows_keep_progress_checkpoint_and_audio_clock(self):
        root = ROOT / 'data/test-runs' / uuid4().hex
        work = root / 'job/work'
        work.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root)
        source = root / 'audio.wav'
        source.write_bytes(audio_bytes(62))
        instance = GeminiProvider({'transcription_provider': 'xai', 'transcription_model': 'grok-voice-transcribe-2.0',
                                  'api_keys': {'xai': 'test-key'}})
        progress = []
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200, json={'words': CUES})
        with patch.dict(os.environ, {'PAID_LLM_ENABLED': 'true', 'MIN_FREE_SPACE_BYTES': '0'}), \
                patch.object(transport.httpx, 'AsyncClient', return_value=client), capture_calls(root, work / 'traces'):
            result = instance.transcribe(source, 'ja', lambda: None, work=work, progress=progress.append)
            self.assertEqual([cue.start for cue in result], [.1, 60.1])
            self.assertEqual(progress[-1]['completed'], 2)
            instance.transcribe(source, 'ja', lambda: None, work=work)
            self.assertEqual(client.post.call_count, 2)
        traces = list((work / 'traces').glob('*/request.json'))
        self.assertEqual(len(traces), 2)
        trace = json.loads(traces[0].read_text())
        self.assertEqual(trace['provider'], 'xai')
        self.assertIn('sha256', trace['payload']['audio']['file'])
        self.assertNotIn('test-key', json.dumps(trace))
