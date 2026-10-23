"""Owner-scoped registry with immutable snapshots and pessimistic CAS writes."""
import re

from ..model_endpoints import (
    FRONTIER_CONNECTIONS,
    canonical_hash,
    connection_contract,
)
from ..model_profile import (
    CAPABILITIES,
    MODALITIES,
    MODEL_TYPES,
    supports_transcription,
    validate_profile,
)
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
        named = row['provider'] in FRONTIER_CONNECTIONS
        official = named and (row['protocol'], row['endpoint']) == FRONTIER_CONNECTIONS[row['provider']]
        return {'id': parent['id'], 'name': row['name'], 'provider': row['provider'], 'protocol': row['protocol'],
                'address_mode': 'official' if official else 'legacy_preserved' if named else 'custom',
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

    def save_connection(self, owner, identity, *, revision, name, provider, protocol=None, endpoint=None):
        resource_id(identity)
        text(name, 80)
        with self.database.connection() as db:
            parent = self._lock(db, 'serving_connections', owner, identity, revision)
            previous = self._connection(db, owner, identity)[1] if parent['revision'] else None
            protocol, endpoint = connection_contract(provider, protocol, endpoint, previous=previous)
            config = {'name': name, 'provider': provider, 'protocol': protocol, 'endpoint': endpoint}
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
                'provider': row['provider'], 'protocol': row['protocol'], 'transcription_supported': supports_transcription(row, row['protocol'], row['remote_model']), 'transcription_format': ('gemini_inline_timed_json' if row['protocol'] == 'gemini' else 'openai_verbose_json_segments') if supports_transcription(row, row['protocol'], row['remote_model']) else None, 'translation_supported': row['protocol'] in ('openai', 'openai_compatible', 'gemini') and 'text_generation' in row['capabilities'], 'connection_id': row['connection_id'], 'connection_revision': row['connection_revision'],
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

    def save_model(self, owner, identity, *, revision, name, model, connection_id, connection_revision, model_types, input_modalities, output_modalities, capabilities, catalog_binding=None):
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
            if config['provider'] in FRONTIER_CONNECTIONS:
                if catalog_binding is not None:
                    if connection['revision'] != config['revision'] or catalog_binding.get('connection_sha256') != config['sha256'] or catalog_binding.get('connection_revision') != config['revision']:
                        raise Conflict('공식 모델 조회 후 공급자 연결이 변경됐습니다. 다시 조회하세요.')
                    if catalog_binding.get('model') != model or catalog_binding.get('profile') != profile:
                        raise ValueError('선택한 공식 모델과 용도가 조회 결과에 일치하지 않습니다.')
                else:
                    old = db.execute('SELECT * FROM model_revisions WHERE owner_id=%s AND model_id=%s AND revision=%s', (owner, identity, parent['revision'])).fetchone() if parent['revision'] else None
                    if not old or old['remote_model'] != model or old['connection_id'] != connection_id or old['connection_revision'] != config['revision'] or any(old[key] != profile[key] for key in profile):
                        raise ValueError('공식 모델 목록을 조회하고 확인된 모델·용도를 선택하세요. 기존 등록의 동일 설정·이름 변경은 보존됩니다.')
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
