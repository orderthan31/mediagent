"""Face-swap drafts; executions reuse the existing Job queue and ownership model."""
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from .repository import FilesystemJobRepository, JobNotFoundError
from .storage import read_json, write_json_atomic
from .models import utc_now_iso

MAX_SOURCE_BYTES = 10 * 1024**2
DEFAULTS = {'reference_frame': 1, 'face_position': -1, 'source_position': -1,
            'distance': .3, 'preset': 'balanced', 'video_codec': 'h264'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class FaceSwapSessions(FilesystemJobRepository):
    def __init__(self, jobs):
        super().__init__(jobs.storage_root / '.faceswap')

    def read_session(self, session_id, owner):
        path = self.job_dir(session_id) / 'session.json'
        if not path.is_file():
            raise JobNotFoundError(session_id)
        record = read_json(path)
        if record['owner_id'] != owner:
            raise JobNotFoundError(session_id)
        return record

    def save_session(self, record):
        write_json_atomic(self.job_dir(record['session_id']) / 'session.json', record)

    def sessions(self, owner, asset_id=None):
        records = [read_json(path) for path in self.storage_root.glob('*/session.json')]
        return [r for r in records if r['owner_id'] == owner and
                (asset_id is None or r['asset_id'] == asset_id)]

    def create(self, asset_id, owner, request_id):
        for record in self.sessions(owner):
            if record['request_id'] == request_id:
                if record['asset_id'] != asset_id:
                    raise ValueError('요청 ID가 다른 영상에 사용되었습니다.')
                return record
        record = {'session_id': uuid4().hex, 'asset_id': asset_id, 'owner_id': owner,
                  'request_id': request_id, 'revision': 0, 'source_file': None,
                  'source_sha256': None, 'settings': dict(DEFAULTS), 'created_at': utc_now_iso()}
        self.save_session(record)
        return record


def reservation(asset, render=False):
    if not render:
        return 128 * 1024**2
    media = asset.get('media', {})
    duration = float(media.get('duration', 0))
    width, height = int(media.get('width', 0)), int(media.get('height', 0))
    if not math.isfinite(duration) or duration <= 0 or min(width, height) <= 0:
        raise ValueError('영상 메타데이터를 다시 분석해야 합니다.')
    # Reserve uncompressed RGB frames (PNG can expand) and input/output allowance.
    rate = media.get('frame_rate') or '60/1'
    try:
        numerator, denominator = map(float, str(rate).split('/'))
        fps = numerator / denominator
    except (ValueError, ZeroDivisionError):
        fps = 60
    if not math.isfinite(fps) or fps <= 0:
        fps = 60
    return math.ceil(duration * max(60, fps) * (width * height * 4 + 4096)) + asset['size_bytes'] * 2 + 128 * 1024**2


def public_capabilities(root):
    path = Path(root) / '.faceswap-capabilities.json'
    if not path.is_file():
        return {'ready': False, 'reason': '얼굴 합성 Worker가 연결되지 않았습니다.', 'presets': []}
    from datetime import datetime, timezone
    data = read_json(path)
    if (datetime.now(timezone.utc) - datetime.fromisoformat(data['checked_at'])).total_seconds() > 120:
        return {**data, 'ready': False, 'reason': '얼굴 합성 Worker의 연결을 확인 중입니다.'}
    return data
