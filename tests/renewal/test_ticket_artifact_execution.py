"""Disposable PostgreSQL/CAS tests of ticket artifacts, not a full media journey."""
import hashlib
import json
import os
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from test_execution import admit
from test_execution import movie as _movie
from test_execution import runtime as _runtime
from test_foundation import admin as _admin
from test_foundation import db as _db
from test_foundation import login
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.translation import TranslationRuntime

admin, db, movie, runtime = _admin, _db, _movie, _runtime


def cpu_definition():
    return {
        'catalog_version': 1, 'revision': 0, 'name': '산출물 저장 경계', 'inputs': {'video': 'video'},
        'nodes': [
            {'id': 'audio', 'type': 'extract_audio', 'options': {}, 'position': {'x': 180, 'y': 50}},
            {'id': 'prepare', 'type': 'preprocess_audio', 'options': {'vad_mode': 'off', 'audio_filter': 'off'}, 'position': {'x': 500, 'y': 50}},
        ],
        'edges': [
            {'id': 'e0', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'audio', 'port': 'video'}},
            {'id': 'e1', 'source': {'node': 'audio', 'port': 'audio'}, 'target': {'node': 'prepare', 'port': 'audio'}},
        ],
    }


def make_cpu(runtime, owner, movie, actor=None):
    actor = actor or owner
    source = runtime.ingest(owner, 'synthetic.mp4', movie)
    saved = runtime.save_definition(owner, uuid4().hex, cpu_definition())
    job = runtime.create(actor, source['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex)
    admit(runtime, actor, job['id'])
    return job


def make_registered(runtime, owner, asset_id):
    credentials = CredentialStore(runtime.database, os.urandom(32))
    registry = Registry(runtime.database)
    cid, mid = uuid4().hex, uuid4().hex
    registry.save_connection(owner, cid, revision=0, name='Isolated adapter', provider='gemini', protocol='gemini', endpoint='http://127.0.0.1:9000/v1')
    credentials.save(owner, cid, revision=1, secret=uuid4().hex)
    registry.save_model(owner, mid, revision=0, name='Synthetic translation', model='gemini-fixture', connection_id=cid, connection_revision=2, model_types=['text'], input_modalities=['text'], output_modalities=['text'], capabilities=['text_generation'])
    calls = []
    def wire(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '["통제된 번역"]'}]}}]})
    runtime.translation_runtime = TranslationRuntime(credentials, transport_factory=lambda: httpx.MockTransport(wire), approved_origins={'http://127.0.0.1:9000'}, mode='controlled_http')
    definition = {'catalog_version': 1, 'revision': 0, 'name': '등록 결과 저장 경계', 'inputs': {'transcript': 'transcript'}, 'nodes': [{'id': 'translated', 'type': 'translate', 'options': {}, 'position': {'x': 180, 'y': 50}, 'model_ref': {'model_id': mid, 'revision': 1}}], 'edges': [{'id': 'e0', 'source': {'node': '$input', 'port': 'transcript'}, 'target': {'node': 'translated', 'port': 'transcript'}}]}
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    job = runtime.create(owner, asset_id, saved['id'], saved['revision'], request_id=uuid4().hex, options={'source_language': 'en', 'target_language': 'ko', 'transcript': [{'start': 0, 'end': 0.4, 'text': 'Synthetic input'}]})
    admit(runtime, owner, job['id'])
    return job, calls


def test_cpu_and_registered_results_have_separate_persisted_ticket_manifests(runtime, admin, movie):
    from app.renewal import create_app
    from video_service.postgres.accounts import Accounts
    owner = admin[0]['id']
    member_password = uuid4().hex
    member = Accounts(runtime.database).create('artifact-reader', member_password, actor_id=owner)
    first = make_cpu(runtime, owner, movie, member['id'])
    first = runtime.run_local(member['id'], first['id'])
    assert first['status'] == 'completed'
    # The new common acceptance boundary must persist a manifest, not rename a URL.
    assert first['artifact_manifest']['reference']['storage_key'].startswith('tickets/' + first['id'] + '/manifests/')
    second, calls = make_registered(runtime, owner, first['asset_id'])
    second = runtime.run_local(owner, second['id'])
    assert second['status'] == 'completed' and len(calls) == 1
    reopened = Execution(runtime.database, runtime.store)
    documents, keys = [], []
    app = create_app(runtime.database, allowed_origins=('http://testserver',), secure_cookies=False, content_store=runtime.store, local_execution=True)
    with TestClient(app) as client:
        login(client, admin)
        for job in (first, second):
            state = reopened.shared_get(owner, job['id'])
            manifest = client.get('/api/renewal/jobs/' + job['id'] + '/manifest?download=true')
            assert manifest.status_code == 200, manifest.text
            assert hashlib.sha256(manifest.content).hexdigest() == state['artifact_manifest']['reference']['sha256']
            document = manifest.json()
            documents.append(document)
            assert document['ticket_id'] == job['id'] and document['uploaded_by'] == owner and document['executed_by'] == job['owner_id']
            assert state['artifact_manifest']['entry_count'] == len(document['entries'])
            with runtime.database.connection() as connection:
                rows = connection.execute('SELECT storage_key FROM artifacts WHERE job_id=%s', (job['id'],)).fetchall()
                assert sorted(row['storage_key'] for row in rows) == sorted(entry['storage']['storage_key'] for entry in document['entries'])
            assert not any(field in json.dumps(document) for field in ('credential_ref', 'api_key', 'model_bindings', 'engine_bindings', 'endpoint'))
            for entry in document['entries']:
                assert entry['ticket_id'] == job['id'] and entry['attempt'] == 1
                assert entry['storage']['storage_key'].startswith('tickets/' + job['id'] + '/nodes/')
                keys.append(entry['storage']['storage_key'])
                location = runtime.store.path(job['owner_id'], entry['storage'])
                original = runtime.store.path(job['owner_id'], entry['reference'])
                assert os.path.samefile(location, original)
                response = client.get(f'/api/renewal/jobs/{job["id"]}/artifacts/{entry["node_run_id"]}/{entry["output_port"]}?download=true')
                assert response.status_code == 200 and response.content == location.read_bytes()
                assert hashlib.sha256(response.content).hexdigest() == entry['storage']['sha256']
                assert reopened.shared_file(owner, job['id'], entry['node_run_id'], entry['output_port'])[0] == location
        assert {entry['stage'] for entry in documents[0]['entries']} == {'intermediate', 'final'}
        assert len(keys) == len(set(keys))
        entry = documents[0]['entries'][0]
        assert client.get(f'/api/renewal/jobs/{second["id"]}/artifacts/{entry["node_run_id"]}/{entry["output_port"]}').status_code == 404
    with TestClient(app) as reader:
        login(reader, (member, member_password))
        assert reader.get('/api/renewal/jobs/' + second['id'] + '/manifest').status_code == 200
        assert reader.get('/api/settings/serving-connections').status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/renewal/jobs/' + first['id'] + '/manifest').status_code == 401
    export_evidence(first, second, documents)


def export_evidence(first, second, documents):
    target = os.environ.get('MIDEAGENT_ARTIFACT_EVIDENCE')
    if target:
        from pathlib import Path
        Path(target).mkdir(parents=True, exist_ok=True)
        (Path(target) / 'ticket-artifact-result.json').write_text(json.dumps({'scope': 'actual disposable PG/local CAS/CPU subprocess + registered adapter MockTransport, no provider or MQ', 'tickets': [first['id'], second['id']], 'manifests': documents}, ensure_ascii=False, indent=2))


def review_definition():
    return {'catalog_version': 1, 'revision': 0, 'name': '저장 결속 검수', 'inputs': {'transcript': 'transcript'},
            'nodes': [
                {'id': 'choose', 'type': 'select', 'options': {'data_type': 'transcript', 'selection': 'a'}, 'position': {'x': 180, 'y': 50}},
                {'id': 'review', 'type': 'review', 'options': {'data_type': 'transcript'}, 'position': {'x': 500, 'y': 50}},
            ], 'edges': [
                {'id': 'e0', 'source': {'node': '$input', 'port': 'transcript'}, 'target': {'node': 'choose', 'port': 'value'}},
                {'id': 'e1', 'source': {'node': 'choose', 'port': 'a'}, 'target': {'node': 'review', 'port': 'value'}},
            ]}


def make_review(runtime, owner, movie):
    source = runtime.ingest(owner, 'review-synthetic.mp4', movie)
    definition = runtime.save_definition(owner, uuid4().hex, review_definition())
    job = runtime.create(owner, source['asset_id'], definition['id'], definition['revision'], request_id=uuid4().hex,
                         options={'transcript': [{'start': 0, 'end': 0.4, 'text': 'Synthetic input'}]})
    admit(runtime, owner, job['id'])
    return runtime.run_local(owner, job['id'])


def test_control_and_review_receipts_are_bound_to_the_ticket(runtime, admin, movie):
    owner = admin[0]['id']
    job = make_review(runtime, owner, movie)
    assert job['status'] == 'review_required'
    review = job['reviews'][0]
    saved = runtime.review_save(owner, review['id'], review['revision'], {'approved': True})
    runtime.review_confirm(owner, review['id'], saved['revision'])
    document = json.loads(runtime.shared_manifest(owner, job['id']))
    assert {entry['node_id'] for entry in document['entries']} == {'choose', 'review'}


def test_reused_receipt_gets_child_storage_without_rewriting_parent(runtime, admin, movie):
    owner = admin[0]['id']
    job = make_review(runtime, owner, movie)
    runtime.cancel(owner, job['id'], job['revision'])
    original = runtime.shared_manifest(owner, job['id'])
    child = runtime.recover(owner, job['id'], uuid4().hex, acknowledge_duplicate_risk=True)
    child_document = json.loads(runtime.shared_manifest(owner, child['id']))
    assert child_document['entries'] and all(entry['ticket_id'] == child['id'] for entry in child_document['entries'])
    assert runtime.shared_manifest(owner, job['id']) == original
    assert all(entry['storage']['storage_key'].startswith('tickets/' + child['id'] + '/') for entry in child_document['entries'])


def test_legacy_cas_manifest_is_read_only_compatibility(runtime, admin, movie, monkeypatch):
    from video_service.postgres import execution as execution_module
    owner = admin[0]['id']
    original_digest = execution_module.digest
    def legacy_snapshot_digest(value):
        if isinstance(value, dict) and 'artifact_layout' in value and 'asset' in value:
            value.pop('artifact_layout')
        return original_digest(value)
    # Serialize the historical snapshot BEFORE initial INSERT, never UPDATE it.
    with monkeypatch.context() as patch:
        patch.setattr(execution_module, 'digest', legacy_snapshot_digest)
        job = make_cpu(runtime, owner, movie)
    job = runtime.run_local(owner, job['id'])
    assert job['status'] == 'completed' and 'artifact_layout' not in job['snapshot']
    before = {str(path.relative_to(runtime.store.root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in runtime.store.root.rglob('*') if path.is_file()}
    document = json.loads(runtime.shared_manifest(owner, job['id']))
    assert document['layout'] == 'legacy_owner_cas'
    assert job['artifact_manifest']['reference'] is None
    for entry in document['entries']:
        assert entry['storage'] == entry['reference'] and entry['storage']['storage_key'].startswith('blobs/')
        assert runtime.shared_file(owner, job['id'], entry['node_run_id'], entry['output_port'])[0] == runtime.store.path(owner, entry['reference'])
    after = {str(path.relative_to(runtime.store.root)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in runtime.store.root.rglob('*') if path.is_file()}
    assert before == after and not (runtime.store.owner_root(owner) / 'tickets').exists()


def test_cancelled_late_result_is_not_a_manifest_entry_or_normal_download(runtime, admin, movie):
    from app.renewal import create_app
    from video_service.cpu_agents import digest
    owner = admin[0]['id']
    job = make_cpu(runtime, owner, movie)
    command = runtime.claim_next(owner, job['id'])
    result = runtime.execute_command(owner, command)
    assert result['status'] == 'completed'
    current = runtime.get(owner, job['id'])
    runtime.cancel(owner, job['id'], current['revision'])
    quarantined = runtime.accept(owner, command, result)
    assert any(run['status'] == 'quarantined' for run in quarantined['runs'])
    document = json.loads(runtime.shared_manifest(owner, job['id']))
    assert document['entries'] == [] and quarantined['artifact_manifest']['entry_count'] == 0
    with runtime.database.connection() as db:
        rows = db.execute('SELECT message_sha256 FROM result_quarantine WHERE job_id=%s', (job['id'],)).fetchall()
        assert len(rows) == 1 and rows[0]['message_sha256'] == digest(result)
        assert db.execute('SELECT count(*) AS n FROM artifacts WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0
    app = create_app(runtime.database, allowed_origins=('http://testserver',), secure_cookies=False, content_store=runtime.store, local_execution=True)
    with TestClient(app) as client:
        login(client, admin)
        port = next(iter(result['outputs']))
        assert client.get(f'/api/renewal/jobs/{job["id"]}/artifacts/{command["attempt_id"]}/{port}').status_code == 404
    assert not (runtime.store.owner_root(owner) / 'tickets' / job['id']).exists()


def test_uncommitted_storage_alias_is_not_adopted_when_manifest_write_fails(runtime, admin, movie, monkeypatch):
    import pytest
    from video_service.postgres import Missing
    owner = admin[0]['id']
    job = make_cpu(runtime, owner, movie)
    command = runtime.claim_next(owner, job['id'])
    result = runtime.execute_command(owner, command)
    bind = runtime.store.bind_ticket
    published = []
    def fail_manifest(actor, key, reference):
        if '/manifests/' in key:
            raise OSError('synthetic manifest storage failure')
        value = bind(actor, key, reference)
        published.append(value)
        return value
    with monkeypatch.context() as patch:
        patch.setattr(runtime.store, 'bind_ticket', fail_manifest)
        state = runtime.accept(owner, command, result)
    assert published and all(runtime.store.path(owner, ref).is_file() for ref in published)
    assert state['artifact_manifest']['entry_count'] == 0
    assert json.loads(runtime.shared_manifest(owner, job['id']))['entries'] == []
    with pytest.raises(Missing):
        runtime.shared_file(owner, job['id'], command['attempt_id'], next(iter(result['outputs'])))


def test_passthrough_video_keeps_existing_original_preview(runtime, admin, movie):
    owner = admin[0]['id']
    source = runtime.ingest(owner, 'passthrough.mp4', movie)
    definition = {'catalog_version': 1, 'revision': 0, 'name': '영상 참조 보존', 'inputs': {'video': 'video'},
                  'nodes': [{'id': 'choose', 'type': 'select', 'options': {'data_type': 'video', 'selection': 'a'}, 'position': {'x': 180, 'y': 50}}],
                  'edges': [{'id': 'e0', 'source': {'node': '$input', 'port': 'video'}, 'target': {'node': 'choose', 'port': 'value'}}]}
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    job = runtime.create(owner, source['asset_id'], saved['id'], saved['revision'], request_id=uuid4().hex)
    admit(runtime, owner, job['id'])
    job = runtime.run_local(owner, job['id'])
    assert job['status'] == 'completed'
    run = job['runs'][0]
    preview = runtime.shared_file(owner, job['id'], run['id'], 'a', preview=True)[0]
    assert preview.read_bytes() == runtime.web_preview_path(owner, source['asset_id']).read_bytes()
    assert runtime.shared_file(owner, job['id'], run['id'], 'a')[0].read_bytes() == movie
