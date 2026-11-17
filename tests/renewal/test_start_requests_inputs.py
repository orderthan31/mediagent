"""Generic audio and materialized transcript selection on real PostgreSQL."""
from uuid import uuid4
from test_execution import db, admin, movie
from test_start_requests_api import actual_client, raw_request
from test_start_requests import progress
from test_model_role_orchestration import formal
from video_service.canonical import digest


def test_audio_goal_preserves_original_and_language_validation(db, admin, movie, tmp_path):
    from test_audio_original_input import pcm
    from mideagent_orchestrator.workflow import default_definition
    runtime, owner, old = formal(db, admin, movie, tmp_path, prepare=False)
    definition = default_definition()
    model = next(n['model_ref'] for n in old['snapshot']['definition']['nodes'] if n['type'] == 'transcribe')
    definition['nodes'][0]['model_ref'] = model
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    source = runtime.ingest(owner, 'synthetic stereo.wav', pcm())
    client, service = actual_client(runtime, admin)
    options = {'audio_goal': {'node_id': 'transcription', 'options': {'source_language': 'en'}}}
    body = raw_request(client, source, saved, options)
    rid = service.submit_raw(owner, body)['id']
    created = progress(service, owner, rid, 'created')
    job = runtime.get(owner, created['job_id'])
    assert job['snapshot']['asset']['media_kind'] == 'audio'
    assert job['snapshot']['audio_origin_policy']['reference']['type'] == 'audio'
    assert job['snapshot']['options']['source_language'] == 'en'
    assert job['snapshot']['agent_definition']['input_profile'] == 'audio_file_v1'
    original_sha = job['snapshot_sha256']
    progress(service, owner, rid, 'admitted')
    assert runtime.get(owner, job['id'])['snapshot_sha256'] == original_sha
    assert runtime.get(owner, job['id'])['runs'] == []


def test_accepted_audio_revalidated_and_bound_without_placeholder(db, admin, movie, tmp_path):
    from test_execution import graph, admit
    from mideagent_orchestrator.workflow import default_definition
    runtime, owner, old = formal(db, admin, movie, tmp_path, prepare=False)
    asset = runtime.asset(owner, old['asset_id'])
    extraction = runtime.save_definition(owner, uuid4().hex, graph('extract_audio'))
    seed = runtime.create(owner, old['asset_id'], extraction['id'], extraction['revision'], request_id=uuid4().hex)
    admit(runtime, owner, seed['id'])
    seed = runtime.run_local(owner, seed['id'])
    assert seed['status'] == 'completed'
    run = seed['runs'][0]
    model = next(n['model_ref'] for n in old['snapshot']['definition']['nodes'] if n['type'] == 'transcribe')
    definition = default_definition()
    definition.update(inputs={'audio': 'audio'}, nodes=[{**definition['nodes'][0], 'model_ref': model,
        'options': {'audio_source': 'selected_audio', 'source_language': 'en'}}], edges=[])
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    options = {'source_language': 'en', 'accepted_inputs': {'audio': {'job_id': seed['id'], 'run_id': run['id'], 'port': 'audio'}}}
    client, service = actual_client(runtime, admin)
    body = raw_request(client, {'asset_id': old['asset_id']}, saved, options)
    rid = service.submit_raw(owner, body)['id']
    created = progress(service, owner, rid, 'created')
    job = runtime.get(owner, created['job_id'])
    binding = job['snapshot']['normal_input_bindings']['audio']
    assert binding['kind'] == 'accepted' and binding['job_id'] == seed['id']
    assert binding['receipt_sha256'] == digest(run['result'])
    # A second immutable intent must revalidate rather than trust the preview.
    bad = service.submit_raw(owner, {**body, 'request_id': uuid4().hex})['id']
    with runtime.database.connection() as c:
        c.execute("UPDATE jobs SET library_removed_at=now(),library_removed_by=%s,library_removal_reason='synthetic removal' WHERE id=%s", (owner, seed['id']))
    service.process(owner, bad)
    assert service.get(owner, bad)['state'] == 'blocked'
    assert service.get(owner, bad)['job_id'] is None
