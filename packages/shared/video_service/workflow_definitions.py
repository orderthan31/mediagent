"""Owner-scoped editor documents. No ticket migration, execution or model settings."""
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from .locking import _file_lock, JobBusyError
from .workflow_graph import validate_graph


class DefinitionInvalid(ValueError):
    def __init__(self, issues):
        super().__init__('편집 정의의 연결·필수입력·옵션 문제를 해결하세요.')
        self.issues = issues


class DefinitionConflict(Exception):
    pass


class DefinitionStore:
    def __init__(self, root, owner=None):
        scope = 'local' if owner is None else 'owner-' + hashlib.sha256(str(owner).encode()).hexdigest()
        self.directory = Path(root) / '.workflow-definitions' / scope

    def path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
            raise ValueError('편집 정의 ID 형식이 올바르지 않습니다.')
        return self.directory / (identity + '.json')

    def get(self, identity):
        result = json.loads(self.path(identity).read_text(encoding='utf-8'))
        if result.get('id') != identity:
            raise ValueError('저장된 편집 정의를 확인하세요.')
        return result

    def list(self):
        return sorted([{'id': d['id'], 'name': d['name'], 'revision': d['revision'], 'node_count': len(d['nodes'])}
                       for p in self.directory.glob('*.json') for d in [self.get(p.stem)]], key=lambda d: d['name'])

    def save(self, identity, payload):
        target = self.path(identity)
        if not isinstance(payload, dict) or set(payload) != {'catalog_version','revision','name','inputs','nodes','edges'}:
            raise ValueError('편집 정의 필드를 확인하세요.')
        if type(payload['revision']) is not int or payload['revision'] < 0:
            raise ValueError('편집 revision은 0 이상의 정수여야 합니다.')
        if not isinstance(payload['name'], str) or not 1 <= len(payload['name'].strip()) <= 80:
            raise ValueError('이름은 1~80자로 입력하세요.')
        if len(json.dumps(payload, allow_nan=False).encode()) > 131072:
            raise ValueError('편집 정의가 너무 큽니다.')
        validation = validate_graph(payload)
        if not validation['valid']:
            raise DefinitionInvalid(validation['issues'])
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with _file_lock(self.directory / (identity + '.lock')):
                current = self.get(identity)['revision'] if target.exists() else 0
                if current != payload['revision']:
                    raise DefinitionConflict()
                result = {**payload, 'id': identity, 'revision': current + 1, 'name': payload['name'].strip(), 'executable': False}
                temporary = None
                try:
                    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory, prefix='.write-', delete=False) as f:
                        temporary = f.name
                        json.dump(result, f, ensure_ascii=False, allow_nan=False)
                        f.flush(); os.fsync(f.fileno())
                    os.replace(temporary, target)
                finally:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
                return result
        except JobBusyError:
            raise DefinitionConflict() from None
