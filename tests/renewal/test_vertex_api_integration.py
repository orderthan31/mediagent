"""Full ASGI HTTP + native disposable PG acceptance; no provider/network calls.

Uses the existing explicit MIDEAGENT_TEST_DSN/MIDEAGENT_TEST_DISPOSABLE gate
and per-test random schema. Keys are generated synthetic RSA, never real keys.
"""
import json
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.renewal import create_app
from test_foundation import admin, db, login
from test_vertex_contract_validation import account
from video_service.model_endpoints import canonical_hash
from video_service.postgres.accounts import Accounts
from video_service.postgres.credentials import CredentialStore, CredentialUnavailable

BASE = '/api/settings/serving-connections'
ENDPOINT = 'https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/publishers/google'
SENTINEL = 'synthetic-private-request-sentinel'


def metadata(**changes):
    return dict(revision=0, name='Synthetic Vertex', provider='vertex_ai',
                vertex_project='test-project', vertex_location='global', **changes)


@pytest.fixture
def api(db, admin):
    store = CredentialStore(db, os.urandom(32))
    with TestClient(create_app(db, allowed_origins=('http://testserver',),
                              secure_cookies=False, credential_store=store)) as client:
        login(client, admin)
        yield client, store, admin[0]['id']


def create(client, config=None):
    cid = uuid4().hex
    response = client.put(BASE + '/' + cid, json=config or metadata())
    assert response.status_code == 200
    return cid, response.json()


def snapshot(db, owner, cid):
    with db.connection() as conn:
        parent = conn.execute('SELECT * FROM serving_connections WHERE owner_id=%s AND id=%s', (owner, cid)).fetchone()
        revisions = conn.execute('SELECT * FROM connection_revisions WHERE owner_id=%s AND connection_id=%s ORDER BY revision', (owner, cid)).fetchall()
        credentials = conn.execute('SELECT * FROM provider_credentials WHERE owner_id=%s AND connection_id=%s ORDER BY id', (owner, cid)).fetchall()
    return parent, revisions, credentials


def private_response(response, account):
    assert SENTINEL not in response.text
    assert account['private_key'].splitlines()[1] not in response.text
    assert 'BEGIN PRIVATE KEY' not in response.text
    assert 'credential_ref' not in response.text
    assert 'ciphertext' not in response.text


def padded(account, size):
    raw = json.dumps(account, indent=2)
    assert len(raw.encode('utf-8')) < size
    return raw + ' ' * (size - len(raw.encode('utf-8')))


@pytest.mark.parametrize('size', [8192, 32768])
def test_vertex_json_http_encrypt_roundtrip_exact_boundary(db, api, account, caplog, size):
    client, store, owner = api
    cid, created = create(client)
    assert created['endpoint'] == ENDPOINT
    assert created['vertex_project'] == 'test-project'
    assert created['vertex_location'] == 'global'
    assert created['credential'] == 'not_set'
    raw = padded(account, size)
    # Actual nested JSON encoding expands PEM newlines/quotes, not sixfold
    # escaping of every whitespace byte. The existing 64KiB wire cap remains.
    wire = json.dumps({'revision': 1, 'secret': raw}).encode('utf-8')
    assert 4096 < len(raw.encode('utf-8')) <= 32768
    assert size < len(wire) < 65536
    saved = client.put(BASE + '/' + cid + '/credential', content=wire,
                       headers={'Content-Type': 'application/json'})
    assert saved.status_code == 200
    assert saved.json()['revision'] == 2
    assert saved.json()['credential'] == 'reference_set'
    listing = client.get(BASE)
    assert listing.status_code == 200
    assert next(c for c in listing.json()['connections'] if c['id'] == cid) == saved.json()
    for response in (saved, listing):
        private_response(response, account)
    _, revisions, credentials = snapshot(db, owner, cid)
    assert len(revisions) == 2 and len(credentials) == 1
    row = revisions[-1]
    assert (row['vertex_project'], row['vertex_location'], row['endpoint']) == ('test-project', 'global', ENDPOINT)
    assert store.resolve(owner, cid, row['credential_ref']) == raw
    encrypted = bytes(credentials[0]['ciphertext'])
    assert len(encrypted) == size + 12 + 16
    assert raw.encode() not in encrypted
    assert account['private_key'].splitlines()[1].encode() not in encrypted
    assert b'BEGIN PRIVATE KEY' not in encrypted and b'"private_key"' not in encrypted
    assert account['private_key'].splitlines()[1] not in caplog.text


@pytest.mark.parametrize('case', ['duplicate', 'field-type', 'body-type', 'oversize', 'malformed'])
def test_vertex_rejected_secret_is_atomic_and_sanitized(db, api, account, caplog, case):
    client, _, owner = api
    cid, _ = create(client)
    raw = json.dumps(account)
    secret = {
        'duplicate': raw[:-1] + ',"private_key_id":"' + SENTINEL + '"}',
        'field-type': json.dumps({**account, 'client_email': {'sentinel': SENTINEL}}),
        'body-type': {'sentinel': SENTINEL},
        'oversize': padded(account, 32769),
        'malformed': '{"private_key":"' + SENTINEL,
    }[case]
    before = snapshot(db, owner, cid)
    response = client.put(BASE + '/' + cid + '/credential', json={'revision': 1, 'secret': secret})
    assert response.status_code == 422
    private_response(response, account)
    assert snapshot(db, owner, cid) == before
    assert SENTINEL not in caplog.text
    assert account['private_key'].splitlines()[1] not in caplog.text


def test_vertex_endpoint_mismatch_rolls_back_create_and_update(db, api, account):
    client, _, owner = api
    cid = uuid4().hex
    config = metadata(endpoint='https://synthetic.invalid/' + SENTINEL)
    before = snapshot(db, owner, cid)
    response = client.put(BASE + '/' + cid, json=config)
    assert response.status_code == 422
    private_response(response, account)
    assert snapshot(db, owner, cid) == before
    cid, _ = create(client)
    before = snapshot(db, owner, cid)
    response = client.put(BASE + '/' + cid, json={**config, 'revision': 1})
    assert response.status_code == 422
    private_response(response, account)
    assert snapshot(db, owner, cid) == before


def test_vertex_metadata_credential_cas_and_immutable_old_pin(db, api, account):
    client, store, owner = api
    cid, _ = create(client)
    target = BASE + '/' + cid
    raw = padded(account, 8192)
    assert client.put(target + '/credential', json={'revision': 1, 'secret': raw}).status_code == 200
    old = snapshot(db, owner, cid)
    pinned = old[1][-1]
    config = {key: pinned[key] for key in ('name', 'provider', 'protocol', 'endpoint', 'credential_ref', 'vertex_project', 'vertex_location')}
    assert pinned['sha256'] == canonical_hash(config)
    for path, body in [(target, {**metadata(), 'revision': 1}),
                       (target + '/credential', {'revision': 1, 'secret': raw})]:
        response = client.put(path, json=body)
        assert response.status_code == 409
        private_response(response, account)
        assert snapshot(db, owner, cid) == old
    # Credential rotation preserves the old pinned credential and hash.
    rotated = raw + '\n'
    assert client.put(target + '/credential', json={'revision': 2, 'secret': rotated}).status_code == 200
    assert store.resolve(owner, cid, pinned['credential_ref']) == raw
    current = snapshot(db, owner, cid)
    assert current[1][:2] == old[1]
    assert len(current[2]) == 2
    assert store.resolve(owner, cid, current[1][-1]['credential_ref']) == rotated
    changed = client.put(target, json={**metadata(), 'revision': 3,
        'vertex_project': 'other-project', 'vertex_location': 'us-central1'})
    assert changed.status_code == 200
    assert changed.json()['credential'] == 'not_set'
    assert changed.json()['endpoint'] == 'https://us-central1-aiplatform.googleapis.com/v1/projects/other-project/locations/us-central1/publishers/google'
    final = snapshot(db, owner, cid)
    assert final[1][:3] == current[1]
    assert store.resolve(owner, cid, pinned['credential_ref']) == raw
    # Native PG trigger, not a mocked repository assertion.
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.connection() as conn:
            conn.execute('UPDATE connection_revisions SET vertex_location=%s WHERE owner_id=%s AND connection_id=%s AND revision=2', ('us-central1', owner, cid))
    assert snapshot(db, owner, cid) == final


def test_ordinary_key_limit_and_public_hash_shape_unchanged(db, api, account):
    client, store, owner = api
    cid, created = create(client, dict(revision=0, name='Synthetic ordinary', provider='openai_compatible',
                                     protocol='openai_compatible', endpoint='https://synthetic.invalid/v1'))
    assert 'vertex_project' not in created and 'vertex_location' not in created
    before = snapshot(db, owner, cid)
    target = BASE + '/' + cid + '/credential'
    response = client.put(target, json={'revision': 1, 'secret': SENTINEL + 'x' * (4097 - len(SENTINEL))})
    assert response.status_code == 422
    private_response(response, account)
    assert snapshot(db, owner, cid) == before
    secret = 's' * 4096
    saved = client.put(target, json={'revision': 1, 'secret': secret})
    assert saved.status_code == 200
    assert 'vertex_project' not in saved.json() and 'vertex_location' not in saved.json()
    _, rows, _ = snapshot(db, owner, cid)
    row = rows[-1]
    assert row['sha256'] == canonical_hash({k: row[k] for k in ('name', 'provider', 'protocol', 'endpoint', 'credential_ref')})
    assert row['vertex_project'] is None and row['vertex_location'] is None
    assert store.resolve(owner, cid, row['credential_ref']) == secret
    listing = client.get(BASE)
    assert secret not in listing.text
    ordinary = next(c for c in listing.json()['connections'] if c['id'] == cid)
    assert ordinary == saved.json()


def test_native_ciphertext_bound_rejects_oversize_atomically(db, api):
    client, _, owner = api
    cid, _ = create(client)
    before = snapshot(db, owner, cid)
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        with db.connection() as conn:
            conn.execute(
                'INSERT INTO provider_credentials(owner_id,connection_id,id,ciphertext) VALUES (%s,%s,%s,%s)',
                (owner, cid, uuid4().hex, b'x' * (32768 + 12 + 16 + 1)),
            )
    assert caught.value.diag.constraint_name == 'provider_credentials_ciphertext_check'
    assert snapshot(db, owner, cid) == before


def test_vertex_explicit_null_revokes_without_rewriting_history(db, api, account):
    client, store, owner = api
    cid, _ = create(client)
    target = BASE + '/' + cid + '/credential'
    raw = padded(account, 8192)
    assert client.put(target, json={'revision': 1, 'secret': raw}).status_code == 200
    before = snapshot(db, owner, cid)
    reference = before[1][-1]['credential_ref']
    response = client.put(target, json={'revision': 2, 'secret': None})
    assert response.status_code == 200
    assert response.json()['credential'] == 'not_set'
    private_response(response, account)
    after = snapshot(db, owner, cid)
    assert after[1][:2] == before[1]
    assert len(after[1]) == 3 and len(after[2]) == 1
    assert after[2][0]['revoked_at'] is not None
    assert after[1][-1]['vertex_project'] == 'test-project'
    assert after[1][-1]['vertex_location'] == 'global'
    assert after[1][-1]['endpoint'] == ENDPOINT
    with pytest.raises(CredentialUnavailable):
        store.resolve(owner, cid, reference)


def test_vertex_wire_cap_remains_bounded_and_atomic(db, api, account):
    client, _, owner = api
    cid, _ = create(client)
    before = snapshot(db, owner, cid)
    # A legal-sized file deliberately overescaped on the wire is NOT promised
    # acceptance: the independent request body bound must still fail closed.
    raw = padded(account, 32768)
    wire = json.dumps({'revision': 1, 'secret': raw}, separators=(',', ':')).replace(' ', '\\u0020').encode()
    assert json.loads(wire)['secret'] == raw
    assert len(wire) > 65536
    response = client.put(BASE + '/' + cid + '/credential', content=wire,
                          headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    private_response(response, account)
    assert snapshot(db, owner, cid) == before


def test_vertex_auth_csrf_and_ordinary_user_do_not_write(db, api, admin, account):
    client, _, owner = api
    cid, _ = create(client)
    target = BASE + '/' + cid
    credential = {'revision': 1, 'secret': padded(account, 8192)}
    before = snapshot(db, owner, cid)
    for headers in ({'X-CSRF-Token': ''}, {'Origin': 'https://evil.invalid'}):
        for path, body in ((target, {**metadata(), 'revision': 1}), (target + '/credential', credential)):
            response = client.put(path, json=body, headers=headers)
            assert response.status_code == 403
            private_response(response, account)
            assert snapshot(db, owner, cid) == before
    Accounts(db).create('vertex-reader', admin[1], actor_id=owner)
    assert client.post('/api/auth/logout').status_code == 204
    response = client.put(target + '/credential', json=credential)
    assert response.status_code == 401
    private_response(response, account)
    login(client, ({'username': 'vertex-reader'}, admin[1]))
    for path, body in ((target, {**metadata(), 'revision': 1}), (target + '/credential', credential)):
        response = client.put(path, json=body)
        assert response.status_code == 403
        private_response(response, account)
    assert client.get(BASE).status_code == 403
    assert snapshot(db, owner, cid) == before
