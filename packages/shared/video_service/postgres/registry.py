"""Owner-scoped registry with immutable snapshots and pessimistic CAS writes."""
import re

from ..model_endpoints import (
    PROTOCOL_USES,
    PROVIDERS,
    canonical_hash,
    validate_endpoint,
)
from ..model_profile import CAPABILITIES, MODALITIES, MODEL_TYPES, validate_profile
from . import Conflict, Missing


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('리소스 ID 형식 오류')
    return value


def text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('이름 또는 모델 ID 형식 오류')
    return value


class Registry:
    def __init__(self, database):
        self.database = database

    def _lock(self, db, table, owner, identity, expected):
        # table names are constants supplied below, never user-controlled SQL.
        assert table in ('serving_connections', 'registered_models')
        db.execute(f'INSERT INTO {table}(owner_id,id,revision) VALUES (%s,%s,0) ON CONFLICT DO NOTHING', (owner, identity))
        parent = db.execute(f'SELECT * FROM {table} WHERE owner_id=%s AND id=%s FOR UPDATE', (owner, identity)).fetchone()
        if parent['state_revision'] != expected:
            raise Conflict('다른 변경이 저장됐습니다. 편집을 보존하고 최신 항목을 다시 확인하세요.')
        return parent

    def _connection(self, db, owner, identity, revision=None):
        parent = db.execute('SELECT * FROM serving_connections WHERE owner_id=%s AND id=%s', (owner, identity)).fetchone()
        if not parent:
            raise Missing('공급자 연결을 찾을 수 없습니다.')
        row = db.execute('SELECT * FROM connection_revisions WHERE owner_id=%s AND connection_id=%s AND revision=%s',
                         (owner, identity, revision if revision is not None else parent['revision'])).fetchone()
        if not row:
            raise Missing('연결 버전을 찾을 수 없습니다.')
        return parent, row

    @staticmethod
    def _public_connection(parent, row):
        return {'id': parent['id'], 'name': row['name'], 'provider': row['provider'], 'protocol': row['protocol'],
                'endpoint': row['endpoint'], 'revision': parent['state_revision'], 'current_revision': row['revision'],
                'active': parent['active'], 'credential': 'reference_set' if row['credential_ref'] and re.fullmatch(r'db:[a-f0-9]{32}', row['credential_ref']) else 'not_set',
                'sha256': row['sha256'], 'connection_verified': False}

    def connections(self, owner):
        with self.database.connection() as db:
            parents = db.execute('SELECT id FROM serving_connections WHERE owner_id=%s AND revision>0 ORDER BY id', (owner,)).fetchall()
            return [self._public_connection(*self._connection(db, owner, p['id'])) for p in parents]

    def connection(self, owner, identity):
        with self.database.connection() as db:
            return self._public_connection(*self._connection(db, owner, resource_id(identity)))

    def save_connection(self, owner, identity, *, revision, name, provider, protocol, endpoint):
        resource_id(identity)
        text(name, 80)
        if provider not in PROVIDERS or protocol not in PROTOCOL_USES:
            raise ValueError('지원하는 공급자·프로토콜을 선택하세요.')
        endpoint = validate_endpoint(endpoint)
        config = {'name': name, 'provider': provider, 'protocol': protocol, 'endpoint': endpoint}
        with self.database.connection() as db:
            parent = self._lock(db, 'serving_connections', owner, identity, revision)
            previous = self._connection(db, owner, identity)[1] if parent['revision'] else None
            reference = previous['credential_ref'] if previous and all(previous[k] == config[k] for k in ('provider', 'protocol', 'endpoint')) else None
            if reference is not None and not re.fullmatch(r'db:[a-f0-9]{32}', reference):
                reference = None
            config['credential_ref'] = reference
            next_revision = parent['revision'] + 1
            db.execute('INSERT INTO connection_revisions(owner_id,connection_id,revision,name,provider,protocol,endpoint,credential_ref,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (owner, identity, next_revision, name, provider, protocol, endpoint, reference, canonical_hash(config)))
            db.execute('UPDATE serving_connections SET revision=%s,state_revision=state_revision+1 WHERE owner_id=%s AND id=%s', (next_revision, owner, identity))
            result = self._public_connection(*self._connection(db, owner, identity))
        return result

    def compatibility(self, owner, connection_id, connection_revision=None):
        with self.database.connection() as db:
            parent, row = self._connection(db, owner, resource_id(connection_id), connection_revision)
            if not parent['active']:
                return {'model_types': [], 'reason': '사용 중지된 공급자 연결입니다.', 'verified': False}
            return {'model_types': sorted(MODEL_TYPES), 'modalities': sorted(MODALITIES),
                    'capabilities': sorted(CAPABILITIES), 'verified': False,
                    'adapter_capabilities': ['text_generation'] if row['protocol'] in ('openai', 'openai_compatible', 'gemini') else [],
                    'reason': '등록 가능한 메타데이터입니다. 모델 능력·실제 연결은 확인하지 않았습니다.'}

    def _model(self, db, owner, identity):
        parent = db.execute('SELECT * FROM registered_models WHERE owner_id=%s AND id=%s', (owner, identity)).fetchone()
        if not parent:
            raise Missing('등록 모델을 찾을 수 없습니다.')
        versions = {}
        for row in db.execute('SELECT mr.*,cr.provider,cr.protocol FROM model_revisions mr JOIN connection_revisions cr ON cr.owner_id=mr.owner_id AND cr.connection_id=mr.connection_id AND cr.revision=mr.connection_revision WHERE mr.owner_id=%s AND mr.model_id=%s ORDER BY mr.revision', (owner, identity)):
            versions[str(row['revision'])] = {'model_id': identity, 'revision': row['revision'], 'name': row['name'],
                'provider': row['provider'], 'protocol': row['protocol'], 'translation_supported': row['protocol'] in ('openai', 'openai_compatible', 'gemini') and 'text_generation' in row['capabilities'], 'connection_id': row['connection_id'], 'connection_revision': row['connection_revision'],
                'model': row['remote_model'], 'model_types': row['model_types'],
                'input_modalities': row['input_modalities'], 'output_modalities': row['output_modalities'],
                'capabilities': row['capabilities'] if row['model_types'] else [],
                'classification': 'declared' if row['model_types'] else 'legacy_unclassified',
                'sha256': row['sha256']}
        return {'id': identity, 'revision': parent['state_revision'], 'state_revision': parent['state_revision'],
                'current_revision': parent['revision'], 'active': parent['active'],
                'connection': 'unverified', 'versions': versions}

    def models(self, owner):
        with self.database.connection() as db:
            ids = db.execute('SELECT id FROM registered_models WHERE owner_id=%s AND revision>0 ORDER BY id', (owner,)).fetchall()
            return [self._model(db, owner, row['id']) for row in ids]

    def model(self, owner, identity):
        with self.database.connection() as db:
            return self._model(db, owner, resource_id(identity))

    def save_model(self, owner, identity, *, revision, name, model, connection_id, connection_revision, model_types, input_modalities, output_modalities, capabilities):
        resource_id(identity)
        resource_id(connection_id)
        text(name, 80)
        text(model, 200)
        profile = validate_profile(model_types, input_modalities, output_modalities, capabilities)
        with self.database.connection() as db:
            # Serialize deactivation/config writes with admission to this snapshot.
            db.execute('SELECT 1 FROM serving_connections WHERE owner_id=%s AND id=%s FOR UPDATE', (owner, connection_id))
            connection, config = self._connection(db, owner, connection_id, connection_revision)
            if not connection['active']:
                raise Conflict('사용 중지된 공급자 연결입니다.')
            parent = self._lock(db, 'registered_models', owner, identity, revision)
            next_revision = parent['revision'] + 1
            value = {'name': name, 'model': model, 'connection_id': connection_id,
                     'connection_revision': config['revision'], **profile}
            db.execute('INSERT INTO model_revisions(owner_id,model_id,revision,name,remote_model,connection_id,connection_revision,capabilities,model_types,input_modalities,output_modalities,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (owner, identity, next_revision, name, model, connection_id, config['revision'], profile['capabilities'], profile['model_types'], profile['input_modalities'], profile['output_modalities'], canonical_hash(value)))
            db.execute('UPDATE registered_models SET revision=%s,state_revision=state_revision+1 WHERE owner_id=%s AND id=%s', (next_revision, owner, identity))
            result = self._model(db, owner, identity)
        return result

    def availability(self, owner, identity, *, revision, active):
        resource_id(identity)
        with self.database.connection() as db:
            parent = db.execute('SELECT * FROM registered_models WHERE owner_id=%s AND id=%s FOR UPDATE', (owner, identity)).fetchone()
            if not parent:
                raise Missing('등록 모델을 찾을 수 없습니다.')
            if parent['state_revision'] != revision:
                raise Conflict('모델 사용 상태가 변경됐습니다. 최신 항목을 확인하세요.')
            db.execute('UPDATE registered_models SET active=%s,state_revision=state_revision+1 WHERE owner_id=%s AND id=%s', (active, owner, identity))
            result = self._model(db, owner, identity)
        return result
