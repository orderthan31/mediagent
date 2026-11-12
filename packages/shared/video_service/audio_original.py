"""Versioned verified audio originals, distinct from accepted/normalized PCM WAV."""
from copy import deepcopy
import math
import re

ID = 'original_audio_v1'
PROFILE = 'audio_file_v1'
MAX_BYTES = 256 * 1024**2
MAX_SECONDS = 21600


def policy():
    return {'id': ID, 'max_source_bytes': MAX_BYTES, 'max_source_seconds': MAX_SECONDS,
            'normalized_max_bytes': 1024**3}


def validate_media(media, byte_count):
    if (not isinstance(media, dict) or set(media) != {'kind', 'duration', 'format', 'codec', 'sample_rate', 'channels'}
            or media.get('kind') != 'audio' or type(byte_count) is not int or not 0 < byte_count <= MAX_BYTES
            or type(media.get('duration')) not in (int, float) or not math.isfinite(media['duration'])
            or not 0 < media['duration'] <= MAX_SECONDS
            or type(media.get('sample_rate')) is not int or not 8000 <= media['sample_rate'] <= 192000
            or type(media.get('channels')) is not int or not 1 <= media['channels'] <= 8
            or (media.get('format'), media.get('codec')) not in {('wav', 'pcm_s16le'), ('mp3', 'mp3'), ('m4a', 'aac')}
            or media['format'] in {'mp3', 'm4a'} and (media['channels'] > 2 or media['sample_rate'] > 48000)):
        raise ValueError('음성 원본은 검증된 WAV(PCM16)·MP3·M4A(AAC), 256MiB·6시간 이내여야 합니다.')
    return deepcopy(media)


def classify(info, byte_count):
    streams = info.get('streams', [])
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if len(audio) != 1 or any(s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic') for s in streams):
        raise ValueError('음성 stream 하나가 있는 원본이 필요합니다.')
    source = audio[0]
    try:
        container = info['format']['format_name']
        if container not in {'wav', 'mp3'}:
            if (container != 'mov,mp4,m4a,3gp,3g2,mj2'
                    or info['format'].get('tags', {}).get('major_brand') != 'M4A '
                    or source['codec_name'] != 'aac'):
                raise ValueError('Unsupported audio container/codec')
            container = 'm4a'
        media = {'kind': 'audio', 'duration': float(info['format']['duration']),
                 'format': container, 'codec': source['codec_name'],
                 'sample_rate': int(source['sample_rate']), 'channels': source['channels']}
    except (KeyError, TypeError, ValueError):
        raise ValueError('음성 원본의 실제 형식·길이·채널을 확인할 수 없습니다.') from None
    return validate_media(media, byte_count)


def asset_media(asset):
    metadata = asset.get('metadata', {})
    media = metadata.get('media') or {}
    if 'audio_original_policy' not in metadata and media.get('kind') != 'audio':
        return None
    if (metadata.get('registration_state') != 'verified' or metadata.get('audio_original_policy') != policy()
            or metadata.get('media_type') != {'wav': 'audio/wav', 'mp3': 'audio/mpeg', 'm4a': 'audio/mp4'}.get(media.get('format'))):
        raise ValueError('검증된 음성 원본 등록이 필요합니다.')
    return validate_media(media, asset['bytes'])


def verify_path(path, expected, byte_count):
    from mideagent_media_tools.operations import probe_original
    if path.stat().st_size != byte_count or probe_original(path) != validate_media(expected, byte_count):
        raise ValueError('고정 음성 원본의 실제 내용·분류가 다릅니다.')


def frozen_origin(snapshot):
    """Only an exact newly frozen audio asset can be the encoded preprocess input."""
    origin = snapshot.get('audio_origin_policy')
    if origin is None:
        return None
    from .content_store import reference_origin
    from .object_store import validate_reference
    public = snapshot.get('agent_definition', {})
    if (not isinstance(origin, dict) or set(origin) != {'version', 'asset_id', 'custodian_id', 'reference', 'media'}
            or origin['version'] != 1 or public.get('input_profile') != PROFILE
            or snapshot.get('agent_execution_policy') != 1
            or snapshot['definition']['inputs'] != {'audio': 'audio'}
            or [n['type'] for n in snapshot['definition']['nodes']] != ['preprocess_audio', 'transcribe']
            or snapshot['inputs'] != {'audio': origin['reference']}
            or not re.fullmatch('[a-f0-9]{32}', origin['asset_id'])):
        raise ValueError('고정 음성 원본 입력 계약이 다릅니다.')
    owner, ref = reference_origin(origin['custodian_id'], origin['reference'])
    validate_reference(ref)
    asset = snapshot.get('asset', {})
    pin = snapshot.get('normal_input_bindings', {}).get('audio', {})
    if (owner != origin['custodian_id'] or ref['type'] != 'audio'
            or asset.get('asset_id') != origin['asset_id'] or asset.get('uploaded_by') != owner
            or asset.get('media') != origin['media'] or not asset.get('content_verified')
            or pin.get('kind') != 'audio_original' or pin.get('custodian_id') != owner
            or pin.get('asset_id') != origin['asset_id'] or pin.get('content_sha256') != ref['sha256']
            or pin.get('reference') != ref or pin.get('media') != origin['media']
            or pin.get('policy') != policy() or asset.get('audio_original_policy') != policy()):
        raise ValueError('음성 원본 custodian이 다릅니다.')
    prepare, speech = snapshot['definition']['nodes']
    wiring = {(e['source']['node'], e['source']['port'], e['target']['node'], e['target']['port']) for e in snapshot['definition']['edges']}
    if wiring != {('$input', 'audio', prepare['id'], 'audio'), (prepare['id'], 'audio', speech['id'], 'audio'),
                  (prepare['id'], 'timeline', speech['id'], 'timeline')}:
        raise ValueError('전사 음성과 시간 정보는 같은 정규화 결과여야 합니다.')
    validate_media(origin['media'], ref['bytes'])
    return origin
