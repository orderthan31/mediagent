"""Timestamp-capable file STT adapters; never invent timings for text-only output."""
import base64
import io
import wave

from video_service.llm_providers import STT_URLS, valid_stt_model
from .content_block import ContentBlockedError
from .sentence_transcription import validate_sentences
from .translation_transport import ModelRequestError, request_provider


def request_fields(provider, model, language):
    if provider == 'gemini' or not valid_stt_model(provider, model):
        raise ValueError('Unsupported timestamp-capable STT model')
    fields = {'model': model}
    if language != 'auto':
        fields['language'] = language
    if provider == 'xai':
        fields.update(format='true', filler_words='false')
    elif provider == 'openai' and model == 'gpt-4o-transcribe-diarize':
        fields.update(response_format='diarized_json', chunking_strategy='auto')
    else:
        fields.update(response_format='verbose_json')
        fields['timestamp_granularities[]'] = 'segment'
    return fields


def parse_transcription(provider, data, duration, language='auto'):
    if not isinstance(data, dict):
        raise ValueError('STT returned malformed response')
    if data.get('error'):
        error = data['error']
        if isinstance(error, dict) and error.get('code') in ('content_filter', 'content_policy_violation'):
            raise ContentBlockedError('CONTENT_FILTER', provider)
        raise ModelRequestError(f'{provider} STT returned an error response')
    field = 'words' if provider == 'xai' else 'segments'
    items = data.get(field)
    if not isinstance(items, list):
        raise ValueError('STT response is missing subtitle timestamps')
    text = data.get('text', '')
    if not isinstance(text, str):
        raise ValueError('STT returned malformed transcript text')
    if not items and text.strip():
        raise ValueError('STT returned text without subtitle timestamps')
    if provider != 'xai':
        return validate_sentences(items, duration)
    words = validate_sentences(items, duration)
    # xAI provides words, not utterances. Group without changing their clock.
    result = []
    current = None
    separator = '' if language in ('ja', 'zh') or str(data.get('language', '')).split('-')[0] in ('ja', 'zh') else ' '
    for word in words:
        if current and (word['start'] - current['end'] > .8 or word['end'] - current['start'] > 5):
            result.append(current)
            current = None
        if current is None:
            current = dict(word)
        else:
            current['end'] = max(current['end'], word['end'])
            current['text'] += separator + word['text']
        if word['text'].endswith(('.', '?', '!', '\u3002', '\uff01', '\uff1f')):
            result.append(current)
            current = None
    if current:
        result.append(current)
    return validate_sentences(result, duration)


async def request_transcription(provider, key, model, parts, language, check, attempt, retry_delay):
    fields = request_fields(provider, model, language)
    audio = [part['inlineData'] for part in parts if 'inlineData' in part]
    if len(audio) != 1 or audio[0].get('mimeType') != 'audio/wav':
        raise ValueError('STT requires one WAV audio clip')
    raw = base64.b64decode(audio[0]['data'], validate=True)
    if len(raw) > 25_000_000:
        raise ValueError('STT audio clip exceeds upload limit')
    with wave.open(io.BytesIO(raw), 'rb') as stream:
        duration = stream.getnframes() / stream.getframerate()
    return await request_provider(provider, key, model, fields, check, attempt, retry_delay,
        url=STT_URLS[provider], files={'file': ('segment.wav', raw, 'audio/wav')},
        parse=lambda selected, data: parse_transcription(selected, data, duration, language))
