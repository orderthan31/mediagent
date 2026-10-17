"""Declared source metadata only: no file access, uploads, probing or execution."""
import math
import re

from psycopg.types.json import Jsonb
from . import Conflict, Missing
from .registry import resource_id, text


def source_declaration(filename, artifact_ref, byte_count, sha256, media_type, duration_seconds=None):
    text(filename, 255)
    if '/' in filename or '\\' in filename or filename in ('.', '..'):
        raise ValueError('파일 이름에 경로를 넣을 수 없습니다.')
    if not isinstance(sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', sha256):
        raise ValueError('콘텐츠 해시 형식 오류')
    if artifact_ref != 'sha256:' + sha256:
        raise ValueError('불투명 콘텐츠 참조와 해시가 일치해야 합니다.')
    if type(byte_count) is not int or not 0 <= byte_count <= 9223372036854775807:
        raise ValueError('파일 크기 형식 오류')
    if media_type not in ('video/mp4', 'video/webm', 'video/quicktime', 'audio/wav', 'audio/mpeg', 'audio/webm'):
        raise ValueError('지원하는 미디어 유형을 선택하세요.')
    if duration_seconds is not None and (type(duration_seconds) not in (int, float) or not math.isfinite(duration_seconds) or not 0 <= duration_seconds <= 31536000):
        raise ValueError('재생 시간 형식 오류')
    return {'filename': filename, 'storage_key': artifact_ref, 'bytes': byte_count, 'sha256': sha256,
            'metadata': {'media_type': media_type, 'duration_seconds': duration_seconds,
                         'registration_state': 'declared'}}


def public_source(row):
    return {'id': row['id'], 'filename': row['filename'], 'artifact_ref': row['storage_key'],
            'bytes': row['bytes'], 'sha256': row['sha256'],
            'media_type': row['metadata']['media_type'], 'duration_seconds': row['metadata'].get('duration_seconds'),
            'content_verified': False, 'created_at': row['created_at'].isoformat()}


class Sources:
    """Immutable owner-scoped declarations, not proof of existing stored content.

    A future trusted ingestion adapter must verify actual bytes before execution.
    References are content-addressed identifiers, never filesystem paths or URLs.
    """
    def __init__(self, database):
        self.database = database

    def register(self, owner, identity, **body):
        resource_id(identity)
        declaration = source_declaration(**body)
        with self.database.connection() as db:
            db.execute('INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,id) DO NOTHING',
                       (owner, identity, declaration['filename'], declaration['storage_key'], declaration['bytes'],
                        declaration['sha256'], Jsonb(declaration['metadata'])))
            row = db.execute('SELECT * FROM assets WHERE owner_id=%s AND id=%s', (owner, identity)).fetchone()
            if any(row[key] != value for key, value in declaration.items()):
                raise Conflict('같은 원본 ID에 다른 메타데이터를 저장할 수 없습니다.')
            result = public_source(row)
        return result

    def get(self, owner, identity):
        resource_id(identity)
        with self.database.connection() as db:
            row = db.execute('SELECT * FROM assets WHERE owner_id=%s AND id=%s', (owner, identity)).fetchone()
            if not row:
                raise Missing('원본 정보를 찾을 수 없습니다.')
            return public_source(row)

    def list(self, owner, *, page=1, page_size=20):
        if type(page) is not int or type(page_size) is not int or not 1 <= page <= 1000000 or not 1 <= page_size <= 100:
            raise ValueError('페이지 범위 오류')
        with self.database.connection() as db:
            # Count and rows share one snapshot, even when new declarations arrive.
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total = db.execute('SELECT count(*) AS n FROM assets WHERE owner_id=%s', (owner,)).fetchone()['n']
            rows = db.execute('SELECT * FROM assets WHERE owner_id=%s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',
                              (owner, page_size, (page - 1) * page_size)).fetchall()
            return {'sources': [public_source(row) for row in rows], 'total': total,
                    'page': page, 'page_size': page_size, 'content_verified': False}
