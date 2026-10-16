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
        self.root, self.owner = Path(root), owner
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

    def _history_path(self, identity, revision):
        self.path(identity)
        if type(revision) is not int or revision < 1:
            raise ValueError('이력 revision은 1 이상의 정수여야 합니다.')
        return self.directory / '.versions' / identity / (str(revision) + '.json')

    def version(self, identity, revision):
        from .workflow_tickets import digest
        if self.get(identity)['revision'] < revision:
            raise FileNotFoundError('아직 head에 반영되지 않은 저장 이력입니다.')
        row = json.loads(self._history_path(identity, revision).read_text(encoding='utf-8'))
        definition = row['definition']
        if definition['id'] != identity or definition['revision'] != revision or digest(definition) != row['sha256']:
            raise DefinitionConflict('정의 이력의 식별자/내용 무결성이 다릅니다.')
        return row

    def versions(self, identity):
        self.path(identity)
        if not self.path(identity).is_file():return []
        current=self.get(identity)['revision']
        return [{'revision':int(p.stem), **self.version(identity, int(p.stem))} for p in sorted(
            (self.directory / '.versions' / identity).glob('*.json'), key=lambda p: int(p.stem)) if int(p.stem)<=current]

    def restore(self, identity, revision, source, *, snapshot=None):
        from .workflow_tickets import digest
        if source.get('kind') == 'definition_revision' and set(source) == {'kind','revision'}:
            original = self.version(identity, source['revision'])['definition']
            provenance = {'kind':'definition_revision','definition_id':identity,'revision':source['revision'],'sha256':digest(original)}
        elif source.get('kind') == 'ticket_snapshot' and snapshot is not None:
            original = snapshot
            provenance = {**source,'sha256':digest(original)}
        else:
            raise ValueError('서버에 존재하는 정의 이력/티켓 snapshot만 복원할 수 있습니다.')
        payload = {k: original[k] for k in ('catalog_version','name','inputs','nodes','edges')}
        payload['revision'] = revision
        return self.save(identity, payload, provenance=provenance)

    def save(self, identity, payload, *, provenance=None):
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
        from .model_registry import ModelRegistry
        registry=ModelRegistry(self.root,self.owner)
        for node in payload['nodes']:
            if 'model_ref' in node:
                registry.resolve(node['model_ref'],node['type'])
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with _file_lock(self.directory / (identity + '.lock')):
                current = self.get(identity)['revision'] if target.exists() else 0
                if current != payload['revision']:
                    raise DefinitionConflict()
                result = {**payload, 'id': identity, 'revision': current + 1, 'name': payload['name'].strip(), 'executable': False}
                from .workflow_tickets import digest
                from .storage import write_json_atomic
                history = self._history_path(identity, current + 1)
                envelope = {'definition':result,'sha256':digest(result),'source':provenance or {'kind':'editor_save'}}
                if history.exists():
                    if json.loads(history.read_text(encoding='utf-8')) != envelope:
                        raise DefinitionConflict('미완료 저장 이력이 다릅니다. 이력을 덮어쓰지 않습니다.')
                else:
                    write_json_atomic(history, envelope)
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
