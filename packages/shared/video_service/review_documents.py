"""Immutable node-local review revisions; saving is not approval or execution."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import srt
from .locking import _file_lock
from .storage import read_json, write_json_atomic, resolve_under
from .workflow_tickets import digest, TicketConflict
from .review import validate_tracks
from .subtitles import segments_to_srt
from .transcript import TranscriptSegment

LIMIT = 1024 * 1024


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()


class ReviewDocuments:
    def __init__(self, directory, context):
        self.directory = Path(directory).resolve()
        self.context = deepcopy(context)
        self.index = self.directory / 'review.json'

    def _read(self):
        index = read_json(self.index)
        if index['context'] != self.context:
            raise TicketConflict('검수 대상이 다릅니다.')
        return index

    def _view(self, index):
        row = index['versions'][str(index['revision'])]
        path = resolve_under(self.directory, row['document_path'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['document_sha256']:
            raise TicketConflict('검수 수정본 무결성이 변경되었습니다.')
        doc = json.loads(raw)
        if row['output_path']:
            output = resolve_under(self.directory, row['output_path'])
            if hashlib.sha256(output.read_bytes()).hexdigest() != row['sha256']:
                raise TicketConflict('승인할 산출물 bytes가 변경되었습니다.')
        return {**doc, 'target': index['target'], 'revision': index['revision'], 'state_revision': index['state_revision'],
                'sha256': row['sha256'], 'document_sha256': row['document_sha256'], 'approval': deepcopy(index['approval']),
                'status': index['status'], 'request_changes_reason': index.get('request_changes_reason', '')}

    def get(self):
        return self._view(self._read())

    def version(self, revision):
        index = self._read()
        if index['approval'] and index['approval']['revision'] != revision:
            index['approval'] = None
        if revision != self._read()['revision']:
            index['status'] = 'historical'
        index['revision'] = revision
        return self._view(index)

    def _version(self, index, doc, output, capacity_check=None):
        raw = encoded(doc)
        if len(raw) > LIMIT or output is not None and len(output) > LIMIT:
            raise ValueError('검수 문서/수정 결과는 각 1MiB 이하만 지원합니다.')
        if capacity_check:
            capacity_check(len(raw) + len(output or b'') + 4096)
        revision = index['revision']
        relative = 'versions/' + str(revision) + '-' + uuid4().hex
        directory = resolve_under(self.directory, relative)
        directory.mkdir(parents=True)
        (directory / 'document.json').write_bytes(raw)
        output_path = None
        sha = index['source']['sha256']
        if output is not None:
            name = 'output.srt' if doc['kind'] == 'subtitle' else 'output.json'
            (directory / name).write_bytes(output)
            output_path = relative + '/' + name
            sha = hashlib.sha256(output).hexdigest()
        index['versions'][str(revision)] = {'document_path': relative + '/document.json', 'document_sha256': hashlib.sha256(raw).hexdigest(),
                                           'output_path': output_path, 'sha256': sha}
        write_json_atomic(self.index, index)
        return self._view(index)

    def open(self, source, content=None, *, duration=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        with _file_lock(self.directory / 'state.lock'):
            if self.index.exists():
                current = self._read()
                if current['source'] != source:
                    raise TicketConflict('검수 입력 snapshot이 다릅니다.')
                return self._view(current)
            kind = source['type']
            text_kind = kind in {'transcript', 'subtitle'}
            if text_kind and (content is None or len(content) > LIMIT):
                raise ValueError('텍스트 검수 원본은 1MiB 이하만 지원합니다.')
            if content is not None and hashlib.sha256(content).hexdigest() != source['sha256']:
                raise TicketConflict('원본 검수 자료 SHA가 다릅니다.')
            cues = None
            if text_kind:
                if kind == 'transcript':
                    cues = json.loads(content)
                    if not isinstance(cues, list):
                        raise ValueError('전사 검수는 segment 배열만 지원합니다.')
                else:
                    cues = [{'start': x.start.total_seconds(), 'end': x.end.total_seconds(), 'text': x.content} for x in srt.parse(content.decode('utf-8'))]
                if not 1 <= len(cues) <= 10000 or any(not isinstance(c, dict) or not isinstance(c.get('text'), str) for c in cues):
                    raise ValueError('지원하는 검수 구간 형식이 아닙니다.')
            duration_valid = type(duration) in (int, float) and math.isfinite(duration) and duration > 0
            editable = text_kind and source.get('clock', {}).get('basis') == 'original' and duration_valid
            doc = {'kind': kind, 'editable': editable, 'read_only_reason': '' if editable else ('원본 clock 및 검증된 원본 길이의 전사/자막만 수정할 수 있습니다.' if text_kind else '미디어·metadata·timeline·manifest는 확인만 지원합니다.'),
                   'source': deepcopy(source), 'duration': duration, 'cues': cues}
            index = {'context': self.context, 'source': deepcopy(source), 'target': digest({'context': self.context, 'source': source}),
                     'revision': 1, 'state_revision': 1, 'versions': {}, 'approval': None, 'status': 'waiting', 'actions': {}}
            return self._version(index, doc, content if text_kind else None)

    def _check(self, index, state_revision, revision, sha256, target):
        view = self._view(index)
        if (type(state_revision) is not int or type(revision) is not int or view['state_revision'] != state_revision
                or view['revision'] != revision or view['sha256'] != sha256 or view['target'] != target):
            raise TicketConflict('검수 대상/revision/SHA가 변경되었습니다. 편집을 유지하고 명시적으로 다시 조회하세요.')
        return view

    def _validate_cues(self, cues, view):
        if not view['editable']:
            raise ValueError(view['read_only_reason'])
        if not isinstance(cues, list) or len(cues) != len(view['cues']):
            raise ValueError('현재 검수는 기존 구간 수를 유지한 텍스트/시작·끝 수정만 지원합니다.')
        cleaned = []
        for cue, before in zip(cues, view['cues']):
            if (not isinstance(cue, dict) or set(cue) - {'start', 'end', 'text', 'speaker'}
                    or any(type(cue.get(k)) not in (int, float) for k in ('start', 'end'))
                    or not isinstance(cue.get('text'), str) or cue.get('speaker') != before.get('speaker')):
                raise ValueError('구간/텍스트만 수정할 수 있으며 speaker/기타 필드는 바꿀 수 없습니다.')
            cleaned.append(deepcopy(cue))
        validate_tracks({'review': cleaned}, SimpleNamespace(), float(view['duration']), languages={'review': 'auto'})
        return cleaned

    def save(self, state_revision, revision, sha256, target, cues, *, capacity_check=None):
        with _file_lock(self.directory / 'state.lock'):
            index = self._read()
            view = self._check(index, state_revision, revision, sha256, target)
            if index['approval']:
                raise TicketConflict('승인 후 재편집/취소는 지원하지 않습니다. 새 티켓이 필요합니다.')
            cleaned = self._validate_cues(cues, view)
            doc = {k: view[k] for k in ('kind', 'editable', 'read_only_reason', 'source', 'duration')}
            doc['cues'] = cleaned
            output = encoded(cleaned) if view['kind'] == 'transcript' else segments_to_srt([TranscriptSegment.from_dict(c) for c in cleaned]).encode()
            index.update(revision=revision + 1, state_revision=state_revision + 1, status='waiting')
            index.pop('request_changes_reason', None)
            return self._version(index, doc, output, capacity_check)

    def approve(self, state_revision, revision, sha256, target, request_id):
        with _file_lock(self.directory / 'state.lock'):
            index = self._read()
            payload = digest({'state_revision': state_revision, 'revision': revision, 'sha256': sha256, 'target': target})
            if request_id in index['actions']:
                if index['actions'][request_id] != payload:
                    raise TicketConflict('같은 승인 요청 ID의 대상/내용이 다릅니다.')
                return self._view(index)
            view = self._check(index, state_revision, revision, sha256, target)
            if index['approval']:
                raise TicketConflict('이미 확정된 검수입니다.')
            if view['cues'] is not None:
                # This is the same placeholder used by the existing media worker.
                from .review import BLOCKED_TEXT
                if any(BLOCKED_TEXT in cue['text'] for cue in view['cues']):
                    raise ValueError('차단 placeholder를 지원 범위에서 수정한 뒤 명시 승인하세요.')
                if view['editable']:
                    self._validate_cues(view['cues'], view)
            index['approval'] = {'revision': revision, 'sha256': sha256, 'document_sha256': view['document_sha256'],
                                 'input_sha256': index['source']['sha256'], 'target': target, 'request_id': request_id}
            index['actions'][request_id] = payload
            index.update(state_revision=state_revision + 1, status='approved')
            write_json_atomic(self.index, index)
            return self._view(index)

    def request_changes(self, state_revision, revision, sha256, target, request_id, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('수정 요청 사유를 1~2000자로 입력하세요.')
        with _file_lock(self.directory / 'state.lock'):
            index = self._read()
            payload = digest({'action': 'request_changes', 'state_revision': state_revision, 'revision': revision,
                              'sha256': sha256, 'target': target, 'reason': reason})
            if request_id in index['actions']:
                if index['actions'][request_id] != payload:
                    raise TicketConflict('같은 요청 ID에 다른 결정/대상을 사용할 수 없습니다.')
                return self._view(index)
            self._check(index, state_revision, revision, sha256, target)
            if index['approval']:
                raise TicketConflict('승인 후 반려/취소는 지원하지 않습니다. 새 티켓이 필요합니다.')
            index['actions'][request_id] = payload
            index.update(state_revision=state_revision + 1, status='changes_requested', request_changes_reason=reason)
            write_json_atomic(self.index, index)
            return self._view(index)

    def approved_output(self):
        index = self._read()
        view = self._view(index)
        approval = index['approval']
        if not approval or approval['sha256'] != view['sha256'] or approval['revision'] != view['revision']:
            raise TicketConflict('현재 수정본의 명시 승인이 필요합니다.')
        row = index['versions'][str(index['revision'])]
        return (resolve_under(self.directory, row['output_path']) if row['output_path'] else None), deepcopy(approval)
