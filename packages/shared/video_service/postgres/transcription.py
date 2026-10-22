"""Registered timed ASR uses the already-admitted finite candidate runner."""
import re

from ..audio_contract import audio_info, timed_segments
from ..model_endpoints import GeminiAudioAdapter, OpenAIAudioAdapter
from ..model_profile import supports_transcription
from .translation import TranslationRuntime


class TranscriptionRuntime(TranslationRuntime):
    role = 'transcription'

    def available(self, pin):
        return (supports_transcription(pin, pin['protocol'], pin['remote_model'])
                and super().available(pin))

    def make_adapter(self, pin, key):
        adapter_type = GeminiAudioAdapter if pin['protocol'] == 'gemini' else OpenAIAudioAdapter
        return adapter_type(pin['endpoint'], transport=self.transport_factory(),
                            approved_origins=self.approved_origins, api_key=key)

    def transcribe(self, pins, audio, *, source_language, cancelled, record, paid_authorized=False):
        info = audio_info(audio)
        if not isinstance(source_language, str) or not re.fullmatch(r'auto|[a-z]{2,3}', source_language):
            raise ValueError('지원되는 전사 언어를 선택하세요.')
        return self._run(
            pins, invoke=lambda adapter, pin: adapter.transcribe(pin['remote_model'], audio, source_language),
            decode=lambda result: timed_segments(result, info['duration_seconds']),
            cancelled=cancelled, record=record, paid_authorized=paid_authorized,
        )
