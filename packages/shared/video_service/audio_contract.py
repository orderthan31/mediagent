"""Bounded timed-audio contract; never synthesize missing provider timestamps."""
import io
import wave

from .cpu_agents import canonical
from .transcript_input import parse_segments

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 60


def audio_info(raw):
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= MAX_AUDIO_BYTES:
        raise ValueError('전사는 PCM WAV 2MiB/60초 이내만 지원합니다.')
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('전사는 mono/16kHz/PCM16 WAV만 지원합니다.')
            if not 0 < frames <= 16000 * MAX_AUDIO_SECONDS or len(audio.readframes(frames + 1)) != frames * 2:
                raise ValueError('음성 길이/본문이 올바르지 않습니다.')
            return {'duration_seconds': frames / 16000, 'bytes': len(raw), 'format': 'wav_pcm16_mono_16000'}
    except (wave.Error, EOFError):
        raise ValueError('검증 가능한 PCM WAV가 필요합니다.') from None


def timed_segments(value, duration):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError('시간 정보가 있는 전사 구간 1~100개가 필요합니다.')
    result = []
    for row in value:
        if not isinstance(row, dict) or not {'start', 'end', 'text'} <= set(row):
            raise ValueError('전사 응답의 시각/텍스트가 없습니다.')
        result.append({k: row[k] for k in ('start', 'end', 'text', 'speaker') if k in row})
    parse_segments(canonical(result))
    if len(canonical(result)) > 16000 or any(row['end'] > duration for row in result):
        raise ValueError('전사 시각이 실제 음성 범위를 벗어나거나 자막이 16KB를 넘습니다.')
    return result
