"""Synthetic declarations only: no source files, blobs or real media are created."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from test_foundation import db, admin, app_client, login
from video_service.postgres import Conflict, Missing
from video_service.postgres.accounts import Accounts
from video_service.postgres.sources import Sources


def declaration():
    digest = 'a' * 64
    return {'filename': 'synthetic-preview.mp4', 'artifact_ref': 'sha256:' + digest,
            'byte_count': 128, 'sha256': digest, 'media_type': 'video/mp4', 'duration_seconds': 1.5}


def test_source_idempotence_owner_pagination_and_database_identity(db, admin):
    sources, owner, identity = Sources(db), admin[0]['id'], uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: sources.register(owner, identity, **declaration()), [0, 1]))
    assert rows[0] == rows[1] == sources.get(owner, identity)
    assert not rows[0]['content_verified']
    with pytest.raises(Conflict):
        sources.register(owner, identity, **{**declaration(), 'filename': 'different.mp4'})
    other = Accounts(db).create('other-owner', 'synthetic-test-password-only', actor_id=owner)
    with pytest.raises(Missing):
        sources.get(other['id'], identity)
    assert sources.list(other['id'])['total'] == 0
    for _ in range(24):
        sources.register(owner, uuid4().hex, **declaration())
    first, last, beyond = sources.list(owner), sources.list(owner, page=2), sources.list(owner, page=3)
    assert first['total'] == last['total'] == beyond['total'] == 25
    assert len(first['sources']) == 20 and len(last['sources']) == 5 and beyond['sources'] == []
    assert len({row['id'] for row in first['sources'] + last['sources']}) == 25
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.connection() as connection:
            connection.execute('UPDATE assets SET bytes=0 WHERE owner_id=%s AND id=%s', (owner, identity))
    assert db.migrate() == []
    assert sources.get(owner, identity) == rows[0]
    with db.connection() as connection:
        assert connection.execute('SELECT count(*) AS n FROM message_outbox').fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM jobs').fetchone()['n'] == 0


def test_source_api_authenticated_declared_only_and_closed_mutations(db, admin):
    identity = uuid4().hex
    path = '/api/source-metadata/' + identity
    with app_client(db) as client:
        assert client.get('/api/source-metadata').status_code == 401
        login(client, admin)
        assert client.put(path, json=declaration(), headers={'X-CSRF-Token': ''}).status_code == 403
        result = client.put(path, json=declaration())
        assert result.status_code == 200, result.text
        assert client.put(path, json=declaration()).json() == result.json()
        assert client.get(path).json() == result.json()
        assert client.get('/api/source-metadata').json()['total'] == 1
        assert client.put(path, json={**declaration(), 'byte_count': 99}).status_code == 409
        assert client.delete(path, headers={'Content-Type': 'application/json'}).status_code == 405
        assert client.get('/api/source-metadata?page_size=101').status_code == 422
        assert client.get('/api/source-metadata/' + uuid4().hex).status_code == 404
        for body in [
            {**declaration(), 'artifact_ref': '/private/source.mp4'},
            {**declaration(), 'artifact_ref': 'https://example.invalid/private.mp4'},
            {**declaration(), 'filename': '../private.mp4'},
            {**declaration(), 'byte_count': True},
            {**declaration(), 'duration_seconds': True},
            {**declaration(), 'sha256': 'b' * 64},
            {**declaration(), 'media_type': 'text/html'},
            {**declaration(), 'credential': 'synthetic-never-echo'},
        ]:
            response = client.put('/api/source-metadata/' + uuid4().hex, json=body)
            assert response.status_code == 422, response.text
            assert 'synthetic-never-echo' not in response.text
        assert client.get('/api/source-metadata').json()['total'] == 1
        assert client.get('/api/videos').status_code == 404
        assert client.post('/api/jobs', json={}).status_code == 404
