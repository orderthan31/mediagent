"""Independent immutable SRT documents. No job, review, model or DB dependency."""
from datetime import datetime, timezone
import hashlib
import json
import re

from .canonical import canonical
from .content_store import ID, HEX, valid_content_key

MAX_SRT = 16 * 1024 * 1024
MAX_RECEIPT = 16384
PAGE_SIZE = 20
CLOCK = re.compile(
    r'(\d{2,5}:[0-5][0-9]:[0-5][0-9],[0-9]{3}) --> '
    r'(\d{2,5}:[0-5][0-9]:[0-5][0-9],[0-9]{3})\Z'
)


def identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid subtitle copy identity')
    return value


def label(value, *, filename=False):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
        or any(ord(c) < 32 for c in value)
        or (filename and (value in {'.', '..'} or any(c in value for c in '/\\:')))
    ):
        raise ValueError('자막 제목·파일명을 확인하세요.')
    return value


def validate_srt(text):
    if not isinstance(text, str):
        raise ValueError('SRT 문구가 필요합니다.')
    try:
        raw = text.encode('utf8')
    except UnicodeError:
        raise ValueError('UTF-8 자막이 필요합니다.') from None
    if not 0 < len(raw) <= MAX_SRT:
        raise ValueError('자막은 16MiB 이내여야 합니다.')
    # Match the direct editor/producer contract without renumbering or reserializing.
    lines = re.split(r'\r\n|\r|\n', text.removeprefix('\ufeff'))
    ids, index = set(), 0

    def valid_id(value):
        return bool(value) and not any(ord(c) < 32 for c in value) and (
            len(value) <= 128
            or re.fullmatch(r'-?(?:0|[1-9][0-9]*)', value) is not None
        )

    def time(value):
        h, m, s, ms = map(int, re.split('[:,]', value))
        return ((h * 60 + m) * 60 + s) * 1000 + ms

    while index < len(lines):
        candidate = lines[index]
        if re.fullmatch('[ \t]*', candidate) and not (
            valid_id(candidate)
            and index + 1 < len(lines)
            and CLOCK.fullmatch(lines[index + 1])
        ):
            index += 1
            continue
        if not valid_id(candidate) or candidate in ids or index + 1 >= len(lines):
            raise ValueError('자막 번호·중복을 확인하세요.')
        match = CLOCK.fullmatch(lines[index + 1])
        if not match or time(match[1]) >= time(match[2]):
            raise ValueError('자막 시작·종료 시각을 확인하세요.')
        index += 2
        first = index
        while index < len(lines) and not re.fullmatch('[ \t]*', lines[index]):
            if CLOCK.fullmatch(lines[index]) or any(ord(c) < 32 and c != '\t' for c in lines[index]):
                raise ValueError('자막 문구·구간 사이의 빈 줄을 확인하세요.')
            index += 1
        if index == first or not '\n'.join(lines[first:index]).strip():
            raise ValueError('자막 문구가 필요합니다.')
        ids.add(candidate)
        if len(ids) > 10000:
            raise ValueError('자막은 10000개 이내여야 합니다.')
    if not ids:
        raise ValueError('시각과 문구가 있는 SRT 파일이 필요합니다.')
    return raw, len(ids)


def encode_receipt(receipt):
    raw = canonical({
        'receipt': receipt,
        'sha256': hashlib.sha256(canonical(receipt)).hexdigest(),
    })
    if len(raw) > MAX_RECEIPT:
        raise ValueError('Subtitle copy receipt too large')
    return raw


def decode_receipt(raw, id):
    try:
        envelope = json.loads(raw)
        receipt = envelope['receipt']
        ref = receipt['reference']
        if (
            set(envelope) != {'receipt', 'sha256'}
            or canonical(envelope) != raw
            or envelope['sha256'] != hashlib.sha256(canonical(receipt)).hexdigest()
            or set(receipt) != {
                'version', 'id', 'actor_id', 'filename', 'title', 'created_at',
                'cue_count', 'reference',
            }
            or receipt['version'] != 1
            or identity(receipt['id']) != id
            or not identity(receipt['actor_id'])
            or not label(receipt['filename'], filename=True)
            or not label(receipt['title'])
            or type(receipt['cue_count']) is not int
            or not 1 <= receipt['cue_count'] <= 10000
            or datetime.fromisoformat(receipt['created_at']).utcoffset() is None
            or set(ref) != {'storage_key', 'sha256', 'bytes', 'type'}
            or not isinstance(ref['sha256'], str)
            or not HEX.fullmatch(ref['sha256'])
            or not valid_content_key(ref['storage_key'], ref['sha256'])
            or ref['storage_key'] != 'blobs/' + ref['sha256']
            or ref['type'] != 'subtitle'
            or type(ref['bytes']) is not int
            or not 0 < ref['bytes'] <= MAX_SRT
        ):
            raise ValueError('Invalid subtitle copy receipt')
        return receipt
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('Invalid subtitle copy receipt') from None


def public(receipt):
    return {k: receipt[k] for k in ('id', 'filename', 'title', 'created_at', 'cue_count')}


class SubtitleCopies:
    def __init__(self, store):
        self.store = store

    def save(self, actor, *, id, filename, title, srt):
        identity(actor)
        identity(id)
        label(filename, filename=True)
        label(title)
        raw, count = validate_srt(srt)
        reference = self.store.put(actor, [raw], 'subtitle', max_bytes=MAX_SRT)
        receipt = dict(
            version=1, id=id, actor_id=actor, filename=filename, title=title,
            created_at=datetime.now(timezone.utc).isoformat(),
            cue_count=count, reference=reference,
        )
        stored = decode_receipt(
            self.store.create_subtitle_copy(id, encode_receipt(receipt)), id
        )
        # Same ID may only acknowledge the same immutable request; never overwrite.
        if (
            {k: v for k, v in stored.items() if k != 'created_at'}
            != {k: v for k, v in receipt.items() if k != 'created_at'}
        ):
            raise ValueError('Subtitle copy identity collision')
        self.get(id)  # Verify persisted receipt AND CAS bytes before acknowledgment.
        return public(stored)

    def get(self, id):
        receipt = decode_receipt(self.store.read_subtitle_copy(identity(id)), id)
        raw = self.store.read(receipt['actor_id'], receipt['reference'], limit=MAX_SRT)
        try:
            text = raw.decode('utf8')
        except UnicodeError:
            raise ValueError('Invalid saved UTF-8 subtitle') from None
        _, count = validate_srt(text)
        if count != receipt['cue_count']:
            raise ValueError('Subtitle copy cue count differs')
        return {**public(receipt), 'srt': text}

    def list(self, after=None):
        if after is not None:
            identity(after)
        ids, more = self.store.list_subtitle_copies(after)
        copies = [public(decode_receipt(self.store.read_subtitle_copy(id), id)) for id in ids]
        return {'copies': copies, 'next_cursor': ids[-1] if more and ids else None}
