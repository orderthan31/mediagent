"""Owner-scoped registry with immutable snapshots and pessimistic CAS writes."""
import re
from ..model_endpoints import canonical_hash, validate_endpoint, PROVIDERS, PROTOCOL_USES
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
                'active': parent['active'], 'credential': 'reference_set' if row['credential_ref'] else 'not_set',
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
            next_revision = parent['revision'] + 1
            db.execute('INSERT INTO connection_revisions(owner_id,connection_id,revision,name,provider,protocol,endpoint,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       (owner, identity, next_revision, name, provider, protocol, endpoint, canonical_hash(config)))
            db.execute('UPDATE serving_connections SET revision=%s,state_revision=state_revision+1 WHERE owner_id=%s AND id=%s', (next_revision, owner, identity))
            result = self._public_connection(*self._connection(db, owner, identity))
        return result

    def compatibility(self, owner, connection_id, connection_revision=None):
        with self.database.connection() as db:
            parent, row = self._connection(db, owner, resource_id(connection_id), connection_revision)
            if not parent['active']:
                return {'uses': [], 'reason': '사용 중지된 공급자 연결입니다.', 'verified': False}
            return {'uses': list(PROTOCOL_USES[row['protocol']]), 'verified': False,
                    'reason': '구현된 텍스트 어댑터 기준입니다. 실제 서버·모델 연결은 검사하지 않았습니다.'}

    def _model(self, db, owner, identity):
        parent = db.execute('SELECT * FROM registered_models WHERE owner_id=%s AND id=%s', (owner, identity)).fetchone()
        if not parent:
            raise Missing('등록 모델을 찾을 수 없습니다.')
        versions = {}
        for row in db.execute('SELECT mr.*,cr.provider FROM model_revisions mr JOIN connection_revisions cr ON cr.owner_id=mr.owner_id AND cr.connection_id=mr.connection_id AND cr.revision=mr.connection_revision WHERE mr.owner_id=%s AND mr.model_id=%s ORDER BY mr.revision', (owner, identity)):
            versions[str(row['revision'])] = {'model_id': identity, 'revision': row['revision'], 'name': row['name'],
                'provider': row['provider'], 'connection_id': row['connection_id'], 'connection_revision': row['connection_revision'],
                'model': row['remote_model'], 'uses': row['capabilities'], 'sha256': row['sha256']}
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

    def save_model(self, owner, identity, *, revision, name, model, connection_id, connection_revision, uses):
        resource_id(identity)
        resource_id(connection_id)
        text(name, 80)
        text(model, 200)
        with self.database.connection() as db:
            # Serialize deactivation/config writes with admission to this snapshot.
            db.execute('SELECT 1 FROM serving_connections WHERE owner_id=%s AND id=%s FOR UPDATE', (owner, connection_id))
            connection, config = self._connection(db, owner, connection_id, connection_revision)
            if not connection['active']:
                raise Conflict('사용 중지된 공급자 연결입니다.')
            if not uses or len(set(uses)) != len(uses) or not set(uses) <= set(PROTOCOL_USES[config['protocol']]):
                raise ValueError('선택한 연결에서 구현되지 않은 모델 용도입니다.')
            parent = self._lock(db, 'registered_models', owner, identity, revision)
            next_revision = parent['revision'] + 1
            value = {'name': name, 'model': model, 'connection_id': connection_id,
                     'connection_revision': config['revision'], 'uses': sorted(uses)}
            db.execute('INSERT INTO model_revisions(owner_id,model_id,revision,name,remote_model,connection_id,connection_revision,capabilities,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (owner, identity, next_revision, name, model, connection_id, config['revision'], sorted(uses), canonical_hash(value)))
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
