"""New audio original verticals: actual source methods, fake SQL, tiny offline media."""
import ast
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import math
import os
from pathlib import Path
import struct
import sys
from types import MethodType, ModuleType, SimpleNamespace
from uuid import uuid4
import wave

import pytest
from test_saved_subtitle_translation import mt, state, connected, recovery_runtime, source_execution, PRIMARY, FALLBACK, LLM

ROOT = Path(__file__).resolve().parents[2]
for project in ('packages/shared', 'agents', 'apps/orchestrator', 'tools/media'):
    sys.path.insert(0, str(ROOT / project))
OWNER, ACTOR = 'a' * 32, 'b' * 32
TOOLS = Path('C:/Users/skygg/AppData/Local/hermes/tools/ffmpeg-9.0.1-win32-x64/bin')


def pcm():
    data = io.BytesIO()
    with wave.open(data, 'wb') as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(44100)
        stream.writeframes(b''.join(struct.pack('<hh', int(8000 * math.sin(i * 2 * math.pi * 440 / 44100)), 0) for i in range(8820)))
    return data.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch):
    from video_service.content_store import ContentStore
    if os.name == 'nt':
        chmod = Path.chmod
        def mode(path, value, *a, **kw):
            if value == 0o400 and path.is_relative_to(tmp_path): return
            return chmod(path, value, *a, **kw)
        monkeypatch.setattr(Path, 'chmod', mode)
    monkeypatch.setenv('PATH', str(TOOLS) + os.pathsep + os.environ.get('PATH', ''))
    return ContentStore(tmp_path)


def intake_methods(names):
    from video_service.canonical import digest
    from video_service.original_upload_policy import MAX_ORIGINAL_UPLOAD, ORIGINAL_UPLOAD_LIMIT_MESSAGE
    from mideagent_media_tools import operations
    path = ROOT / 'packages/shared/video_service/postgres/intake.py'
    tree = ast.parse(path.read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Intake')
    ns = dict(__package__='video_service.postgres', uuid4=uuid4, Jsonb=lambda value: deepcopy(value), digest=digest,
              resource_id=lambda value: value, Conflict=ValueError, Missing=LookupError,
              MAX_ORIGINAL_UPLOAD=MAX_ORIGINAL_UPLOAD, ORIGINAL_UPLOAD_LIMIT_MESSAGE=ORIGINAL_UPLOAD_LIMIT_MESSAGE,
              MAX_CONTENT=268435456, probe=operations.probe, process=operations.process, ffmpeg=operations.ffmpeg,
              tempfile=__import__('tempfile'))
    # Include the actual module functions used by these production methods.
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'public_upload', 'public_asset'}]
    methods = [deepcopy(n) for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in methods: node.decorator_list = []
    exec(compile(ast.Module(body=[*functions, *methods], type_ignores=[]), str(path), 'exec'), ns)
    return ns


@pytest.fixture
def registration(store, monkeypatch):
    raw = pcm()
    part = store.put(OWNER, [raw], 'upload_part')
    row = dict(id='c' * 32, owner_id=OWNER, filename='actual stereo.wav', expected_size=len(raw),
               uploaded_bytes=len(raw), asset_id=None, created_at=datetime.now(timezone.utc))
    assets = []
    class Guard:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def transaction(self): return nullcontext()
        def execute(self, sql, params=None):
            result = None
            if 'pg_try_advisory_lock' in sql or 'pg_locks' in sql: result = {'yes': True}
            elif sql.startswith('SET LOCAL'): pass
            elif sql.startswith('INSERT INTO assets'):
                assets.append(dict(owner_id=params[0], id=params[1], filename=params[2], storage_key=params[3], bytes=params[4], sha256=params[5], metadata=params[6], created_at=row['created_at']))
            elif sql.startswith('UPDATE source_uploads SET asset_id'):
                row['asset_id'] = params[0]; result = deepcopy(row)
            else: raise AssertionError(sql)
            return SimpleNamespace(fetchone=lambda: result)
    psycopg = ModuleType('psycopg'); psycopg.connect = lambda *a, **kw: Guard()
    rows = ModuleType('psycopg.rows'); rows.dict_row = object()
    monkeypatch.setitem(sys.modules, 'psycopg', psycopg); monkeypatch.setitem(sys.modules, 'psycopg.rows', rows)
    preview = ModuleType('video_service.postgres.video_previews')
    preview.VideoPreviews = lambda *a: pytest.fail('audio registration must not enqueue a video preview')
    monkeypatch.setitem(sys.modules, preview.__name__, preview)
    ns = intake_methods({'upload_complete', 'asset_reference'})
    runtime = SimpleNamespace(store=store, database=SimpleNamespace(dsn='synthetic-no-connection'), full_previews_enabled=True,
        _upload=lambda *a, **kw: deepcopy(row), _parts=lambda *a: [part], _blocks=lambda *a: [raw])
    runtime.upload_complete = MethodType(ns['upload_complete'], runtime)
    return SimpleNamespace(runtime=runtime, assets=assets, row=row, raw=raw, ns=ns)


def test_real_original_completion_registers_audio_bytes_without_video_derivatives(registration):
    state = registration
    completed = state.runtime.upload_complete(OWNER, state.row['id'])
    assert completed['asset_id'] and len(state.assets) == 1
    asset = state.assets[0]
    assert asset['sha256'] == hashlib.sha256(state.raw).hexdigest() and asset['bytes'] == len(state.raw)
    assert asset['metadata']['media_type'] == 'audio/wav'
    assert asset['metadata']['media']['sample_rate'] == 44100 and asset['metadata']['media']['channels'] == 2
    assert 'width' not in asset['metadata']['media'] and not asset['metadata'].get('thumbnail')
    assert state.ns['asset_reference'](asset)['type'] == 'audio'
    public = state.ns['public_asset'](asset)
    assert public['media_kind'] == 'audio' and public['uploaded_by'] == OWNER
    assert state.runtime.upload_complete(OWNER, state.row['id']) == completed and len(state.assets) == 1


@pytest.mark.parametrize('change', ['cancelled', 'incomplete'])
def test_original_completion_still_refuses_cancelled_or_incomplete(registration, change):
    if change == 'cancelled': registration.row['cancelled_at'] = 'synthetic cancellation'
    else: registration.row['uploaded_bytes'] -= 1
    with pytest.raises(ValueError): registration.runtime.upload_complete(OWNER, registration.row['id'])
    assert registration.assets == []


def test_audio_goal_selection_compiles_only_preprocess_then_transcribe():
    from mideagent_orchestrator.workflow import default_definition, selected_definition, compile_definition
    source = default_definition()
    source['nodes'][0]['model_ref'] = {'model_id': '1' * 32, 'revision': 7}
    before = deepcopy(source)
    chosen = selected_definition(source, {'audio_goal': {'node_id': 'transcription', 'options': {'source_language': 'ja'}}})
    compiled = compile_definition(chosen)
    assert [n['type'] for n in compiled['definition']['nodes']] == ['preprocess_audio', 'transcribe']
    assert chosen['input_profile'] == 'audio_file_v1' and compiled['definition']['inputs'] == {'audio': 'audio'}
    assert source == before


@pytest.fixture
def audio_runtime(mt, store, monkeypatch, request):
    """Real create/plan/claim/binder, fake registry/queue grants and SQL only."""
    import subprocess
    from mideagent_media_tools.operations import probe_original
    from video_service.canonical import digest
    raw_wav = store.root / 'synthetic.wav'; raw_wav.write_bytes(pcm())
    fixture_options = getattr(request, 'param', {})
    container = fixture_options.get('container', 'mp3')
    source = store.root / ('synthetic.' + container)
    encoding = ['-c:a', 'aac', '-f', 'ipod'] if container == 'm4a' else ['-c:a', 'libmp3lame']
    subprocess.run([str(TOOLS / 'ffmpeg.exe'), '-v', 'error', '-i', str(raw_wav), *encoding, '-b:a', '64k', str(source)], check=True, capture_output=True, timeout=10)
    owner = '8' * 32
    raw = source.read_bytes()
    ref = store.put(owner, [raw], 'audio')
    from video_service.audio_original import policy
    asset = dict(owner_id=owner, id='d' * 32, filename='real-name.' + container, storage_key='sha256:' + ref['sha256'],
                 sha256=ref['sha256'], bytes=len(raw), created_at=datetime.now(timezone.utc),
                 metadata={'registration_state': 'verified', 'media': probe_original(source), 'media_type': 'audio/mp4' if container == 'm4a' else 'audio/mpeg', 'audio_original_policy': policy()})
    runtime = mt.runtime
    runtime.store = store
    ns = intake_methods({'asset_reference','_shared_asset','asset','asset_path'})
    runtime.asset_reference = ns['asset_reference']
    runtime.create.__func__.__globals__['public_asset'] = ns['public_asset']
    for name in ('_shared_asset','asset','asset_path'):
        setattr(runtime,name,MethodType(ns[name],runtime))
    node = mt.definition['nodes'][0]
    node.update(model_ref=deepcopy(PRIMARY), fallback_refs=[deepcopy(FALLBACK)],
                options={'source_language': 'ja', 'llm_options': LLM}, tool_settings={'transcribe': {'max_model_calls': str(fixture_options.get('max_calls', 4)),
                'batch_policy': 'bounded_60s_v1', 'clock_policy': 'packed_projection_v5', 'media_budget': 'audio_long_v5'}})
    for row in mt.rows.values():
        row.update(model_types=['multimodal'], input_modalities=['audio', 'text'],
                   capabilities=['text_generation', 'structured_output', 'speech_recognition'])
    runtime.transcription_runtime = runtime.translation_runtime
    runtime.translation_runtime = None
    # Real strict PCM reader, loaded without the unavailable PG package.
    strict_path = ROOT / 'packages/shared/video_service/postgres/audio_region_reviews.py'
    strict_tree = ast.parse(strict_path.read_text(encoding='utf8'))
    strict = ModuleType('video_service.postgres.audio_region_reviews')
    strict.__dict__.update(wave=wave, KIND='audio_regions_v1')
    funcs = [n for n in strict_tree.body if isinstance(n, ast.FunctionDef) and n.name in {'contract_for', 'interval_field'}]
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(strict_path), 'exec'), strict.__dict__)
    monkeypatch.setitem(sys.modules, strict.__name__, strict)
    execute = runtime.database.execute
    def sql(query, params=()):
        if query.startswith('SELECT * FROM assets WHERE id='):
            return SimpleNamespace(fetchall=lambda: [deepcopy(asset)] if params[0]==asset['id'] and not asset.get('library_removed_at') else [])
        if query.startswith('SELECT request_sha256,inputs FROM node_runs') or query.startswith('SELECT *,lease_expires_at'):
            run = next((r for r in runtime.database.runs[params[1]] if r['id'] == params[2]), None)
            return SimpleNamespace(fetchone=lambda: {**deepcopy(run), 'claim_id': runtime.database.jobs[params[1]]['active_claim_id'], 'lease_valid': True} if run else None)
        if query.startswith('SELECT * FROM model_role_tasks') or query.startswith('SELECT 1 FROM agent_deliveries'):
            return SimpleNamespace(fetchone=lambda: None)
        if query.startswith('SELECT published_at,payload FROM message_outbox'):
            payload = next(p[4] for p in runtime.database.outbox if p[0] == params[2])
            return SimpleNamespace(fetchone=lambda: {'published_at': None, 'payload': payload})
        if query.startswith('INSERT INTO model_role_tasks'):
            grant['envelope'] = deepcopy(params[6]); return SimpleNamespace(fetchone=lambda: None)
        if query.startswith('INSERT INTO message_outbox'):

            runtime.database.outbox.append(params); return SimpleNamespace(fetchone=lambda: None)
        if query.startswith('UPDATE jobs SET status=CASE'):
            return SimpleNamespace(fetchone=lambda: None)
        return execute(query, params)
    runtime.database.execute = sql
    # Existing production claim will execute this grant/availability boundary;
    # no actual PG consent, S3 queue mutation or controller is activated.
    grant = {'allowed': True, 'enrolls': 0}
    class Queue:
        def __init__(self, runtime): pass
        def lock_in(self, db, actor): assert actor == ACTOR
        def requires_in(self, db, job): return True
        def allowed_in(self, db, job, **kw): return grant['allowed']
    queue_module = ModuleType('mideagent_orchestrator.start_queue'); queue_module.StartQueue = Queue
    monkeypatch.setitem(sys.modules, queue_module.__name__, queue_module)
    pool = sys.modules['mideagent_orchestrator.agent_pool'].AgentPool
    pool.enroll_in = lambda *a: grant.update(enrolls=grant['enrolls'] + 1)
    path = ROOT / 'apps/orchestrator/mideagent_orchestrator/execution.py'
    tree = ast.parse(path.read_text(encoding='utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Execution')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_queue_start_reasons_in']
    globals_ = dict(runtime.create.__func__.__globals__)
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), globals_)
    runtime._queue_start_reasons_in = MethodType(globals_['_queue_start_reasons_in'], runtime)
    return SimpleNamespace(runtime=runtime, mt=mt, asset=asset, ref=ref, owner=owner, raw=raw, grant=grant, digest=digest)


def test_real_audio_create_plan_claim_decode_then_asr_command(audio_runtime, tmp_path):
    from video_service.canonical import digest
    from mideagent_media_tools.operations import run
    state = audio_runtime
    runtime = state.runtime
    handlers = state.mt.handlers
    args = dict(asset_id=state.asset['id'], definition_id=state.mt.parent['workflow_id'], definition_revision=1,
                options={'audio_goal': {'node_id': 'transcription', 'options': {'source_language': 'en'}}})
    preview = handlers['preview'](handlers['Selection'](**args), ACTOR)
    assert preview['paid_roles'] == ['transcription'] and preview['model_call_budgets'][0]['max_calls'] == 4
    assert not runtime.database.children
    child = handlers['create'](handlers['Create'](**args, token=preview['token'], request_id='synthetic-audio-only', paid_confirmed=True), ACTOR)
    child['revision'] = 1
    runtime.database.jobs[child['id']] = child
    assert child['asset_id'] == state.asset['id'] and child['snapshot']['asset']['uploaded_by'] == state.owner
    assert child['workflow_owner_id'] == OWNER and child['owner_id'] == ACTOR
    assert set(child['snapshot']['inputs']) == {'audio'}
    assert digest(child['snapshot']['definition']) == preview['execution_definition_sha256']
    verified = runtime._preflight_cpu_inputs(ACTOR, child['id'])
    assert runtime._plan(runtime.database, child, verified)['ready']
    child.update(status='waiting', active_claim_id='6' * 32)
    state.grant['allowed'] = False
    assert runtime.claim_next(ACTOR, child['id']) is None and not runtime.database.runs[child['id']]
    state.grant['allowed'] = True
    command = runtime.claim_next(ACTOR, child['id'])
    assert command['agent'] == {'id': 'preprocess_audio', 'revision': '5'}
    assert command['inputs']['audio']['source_owner_id'] == state.owner and state.grant['enrolls'] == 1
    output = tmp_path / 'synthetic-native-output'; output.mkdir()
    result = run(command, runtime.store.owner_root(ACTOR), output)
    assert result['status'] == 'completed', result
    refs = {port: runtime.store.put(ACTOR, [(output / ref['storage_key']).read_bytes()], ref['type'], max_bytes=1024**3) for port, ref in result['outputs'].items()}
    import json
    clock = json.loads(runtime.store.read(ACTOR, refs['timeline']))
    assert clock['source_sha256'] == state.ref['sha256'] and clock['audio_sha256'] == refs['audio']['sha256']
    assert clock['source_frames'] != len(state.raw) and clock['source_frames'] > 0
    row = runtime.database.runs[child['id']][0]
    row.update(status='completed', result={'status': 'completed', 'outputs': refs})
    asr = runtime.claim_next(ACTOR, child['id'])
    assert asr['agent']['id'] == 'transcribe'
    assert asr['inputs'] == {'audio': refs['audio'], 'timeline': refs['timeline']}
    assert asr['transcription']['source_language'] == 'en' and asr['transcription']['max_model_calls'] == 4
    assert len(asr['transcription']['candidates']) == 2
    path = ROOT/'packages/shared/video_service/postgres/model_roles.py'
    tree=ast.parse(path.read_text(encoding='utf8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ModelRoles')
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_policy_version','_current','enroll','_model_binding'}]
    import json
    from video_service.packed_projection import validate_projection_clock
    ns=dict(__package__='video_service.postgres',deepcopy=deepcopy,json=json,digest=digest,Jsonb=lambda x:deepcopy(x),Conflict=ValueError,validate_projection_clock=validate_projection_clock)
    shell=ast.ClassDef(name='ModelRoles',bases=[],keywords=[],body=methods,decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[shell],type_ignores=[])),str(path),'exec'),ns)
    roles=ns['ModelRoles']();roles.runtime=runtime
    envelope=roles.enroll(ACTOR,asr)
    from video_service.role_task_contracts import validate
    validate(envelope,'result',expected_role='transcription')
    assert envelope['task']['source_language']=='en' and envelope['task']['max_calls']==4
    assert envelope['task']['models'][0]['pin_sha256']==digest(asr['transcription']['candidates'][0])
    assert json.loads(asr['options']['llm_options'])['reasoning_effort']=='high'
    from video_service.long_audio_budget import read_clock
    assert envelope['task']['timeline']==read_clock(clock,audio_sha256=refs['audio']['sha256'])
    assert envelope['source']=={'owner':ACTOR,'reference':refs['audio']} and envelope['output_owner']==ACTOR
    assert state.grant['envelope']==envelope


def create_audio(state, *, options=None, request_id='synthetic-draft'):
    args = dict(asset_id=state.asset['id'], definition_id=state.mt.parent['workflow_id'], definition_revision=1,
                options=options or {'audio_goal': {'node_id': 'transcription', 'options': {'source_language': 'en'}}})
    handlers = state.mt.handlers
    preview = handlers['preview'](handlers['Selection'](**args), ACTOR)
    child = handlers['create'](handlers['Create'](**args, token=preview['token'], request_id=request_id, paid_confirmed=True), ACTOR)
    child['revision'] = 1
    state.runtime.database.jobs[child['id']] = child
    return child


@pytest.mark.parametrize('field,value', [('format','flac'),('codec','aac'),('duration',float('nan')),('duration',21601),('duration',0),('sample_rate',0),('channels',0)])
def test_audio_classification_bounds_are_actual_metadata_not_extension(field, value):
    from video_service.audio_original import validate_media
    media = dict(kind='audio',format='wav',codec='pcm_s16le',duration=1,sample_rate=44100,channels=2)
    media[field] = value
    with pytest.raises(ValueError): validate_media(media,100)


def test_actual_probe_rejects_false_mp3_and_multiple_or_video_streams(store, tmp_path):
    from mideagent_media_tools.operations import probe_original
    from video_service.audio_original import classify, validate_media, MAX_BYTES
    path = tmp_path/'fake.mp3';path.write_bytes(b'not encoded audio')
    with pytest.raises(ValueError): probe_original(path)
    with pytest.raises(ValueError): classify({'streams':[]},100)
    with pytest.raises(ValueError): classify({'streams':[{'codec_type':'audio'},{'codec_type':'audio'}]},100)
    with pytest.raises(ValueError): classify({'streams':[{'codec_type':'audio'},{'codec_type':'video'}]},100)
    with pytest.raises(ValueError): validate_media(dict(kind='audio',format='wav',codec='pcm_s16le',duration=1,sample_rate=44100,channels=2),MAX_BYTES+1)


@pytest.mark.parametrize('change', ['custodian','sha','asset','profile','producer','missing','policy'])
def test_frozen_audio_origin_is_required_and_cannot_relabel_arbitrary_inputs(audio_runtime, change):
    from video_service.canonical import digest
    state=audio_runtime;job=create_audio(state);snapshot=job['snapshot']
    if change=='custodian': snapshot['audio_origin_policy']['custodian_id']=ACTOR
    elif change=='sha': snapshot['normal_input_bindings']['audio']['content_sha256']='0'*64
    elif change=='asset': snapshot['audio_origin_policy']['asset_id']='e'*32
    elif change=='profile': snapshot['agent_definition'].pop('input_profile')
    elif change=='policy': snapshot['normal_input_bindings']['audio']['policy']['max_source_seconds']=999999
    elif change=='producer': snapshot['definition']['edges'][-1]['source']['node']='$input'
    else: snapshot.pop('audio_origin_policy')
    job['snapshot_sha256']=digest(snapshot)
    try:
        verified=state.runtime._preflight_cpu_inputs(ACTOR,job['id'])
        assert not state.runtime._plan(state.runtime.database,job,verified)['ready']
    except (ValueError, KeyError, wave.Error): pass
    assert not state.runtime.database.runs[job['id']]


def test_preprocess_only_encoded_exemption_does_not_relax_normalized_asr_wav(audio_runtime):
    from video_service.canonical import digest
    state=audio_runtime;runtime=state.runtime;job=create_audio(state)
    verified=runtime._preflight_cpu_inputs(ACTOR,job['id'])
    assert runtime._plan(runtime.database,job,verified)['ready']
    changed=deepcopy(verified);changed['snapshot_sha256']='0'*64
    with pytest.raises(ValueError): runtime._checked_input(ACTOR,job,state.ref,changed)
    # A completed producer claiming the compressed ORIGINAL as its normalized
    # audio must be rejected, even though its SHA appears in the origin policy.
    runtime.database.runs[job['id']].append({'status':'completed','result':{'outputs':{'audio':job['snapshot']['inputs']['audio']}}})
    with pytest.raises((ValueError,wave.Error)): runtime._preflight_cpu_inputs(ACTOR,job['id'])


@pytest.mark.parametrize('selector', [ {'node_id':'translation','options':{}}, {'node_id':'transcription','options':{'target_language':'ko'}}, {'node_id':'transcription','options':{},'model_ref':{'model_id':'9'*32,'revision':1}} ])
def test_audio_goal_selector_is_strict_and_no_preview_writes(audio_runtime, selector):
    state=audio_runtime
    args=dict(asset_id=state.asset['id'],definition_id=state.mt.parent['workflow_id'],definition_revision=1,options={'audio_goal':selector})
    with pytest.raises(ValueError): state.mt.handlers['preview'](state.mt.handlers['Selection'](**args),ACTOR)
    assert not state.runtime.database.children and not state.runtime.database.outbox


def test_audio_preview_token_changed_language_or_content_and_unverified_asset_rejected(audio_runtime):
    state=audio_runtime;handlers=state.mt.handlers
    args=dict(asset_id=state.asset['id'],definition_id=state.mt.parent['workflow_id'],definition_revision=1,options={'audio_goal':{'node_id':'transcription','options':{'source_language':'ja'}}})
    preview=handlers['preview'](handlers['Selection'](**args),ACTOR)
    changed=deepcopy(args);changed['options']['audio_goal']['options']['source_language']='en'
    with pytest.raises(ValueError): handlers['create'](handlers['Create'](**changed,token=preview['token'],request_id='stale-audio',paid_confirmed=True),ACTOR)
    state.asset['metadata']['registration_state']='unverified'
    with pytest.raises(ValueError): handlers['preview'](handlers['Selection'](**args),ACTOR)
    assert not state.runtime.database.children


def test_legacy_video_and_selected_wav_compile_contract_remains():
    from mideagent_orchestrator.workflow import default_definition,compile_definition
    source=default_definition();compiled=compile_definition(source)
    assert compiled['definition']['inputs']=={'video':'video'}
    assert [n['type'] for n in compiled['definition']['nodes']][:3]==['analyze','extract_audio','preprocess_audio']
    source['inputs']={'audio':'audio'};source['nodes'][0]['options']['audio_source']='selected_audio'
    reused=compile_definition(source)['definition']
    assert reused['inputs']=={'video':'video','audio':'audio'}
    assert [n['type'] for n in reused['nodes']][:2]==['analyze','preprocess_audio']
    assert 'input_profile' not in source



def test_preview_and_inspect_read_actual_shared_audio_without_writes_or_normalization(audio_runtime, monkeypatch):
    state=audio_runtime;runtime=state.runtime
    monkeypatch.setattr(runtime.store,'put',lambda *a,**k:pytest.fail('preview must not write CAS'))
    import mideagent_media_tools.operations as operations
    monkeypatch.setattr(operations,'run',lambda *a,**k:pytest.fail('preview must not normalize or execute'))
    paid_chains=[]
    def paid(pins):
        paid_chains.append(pins)
        return any(p['model_id']==FALLBACK['model_id'] for p in pins)
    runtime.transcription_runtime.requires_paid=paid
    options={'audio_goal':{'node_id':'transcription','options':{}}}
    inspected=runtime.inspect(ACTOR,state.mt.parent['workflow_id'],1,options=options)
    assert inspected['supported'] and inspected['paid_roles']==['transcription']
    assert all(len(pins)==2 for pins in paid_chains)
    args=dict(asset_id=state.asset['id'],definition_id=state.mt.parent['workflow_id'],definition_revision=1,options=options)
    preview=state.mt.handlers['preview'](state.mt.handlers['Selection'](**args),ACTOR)
    assert preview['paid_roles']==['transcription'] and not runtime.database.children
    state.mt.available['value']=False
    result=runtime.inspect(ACTOR,args['definition_id'],1,options=options)
    assert not result['supported'] and result['reasons']


@pytest.mark.parametrize('change',['unknown','removed'])
def test_actual_shared_asset_lookup_keeps_missing_or_removed_audio_unavailable(audio_runtime,change):
    state=audio_runtime
    assetid=state.asset['id']
    if change=='unknown': assetid='e'*32
    else: state.asset['library_removed_at']='synthetic removal'
    args=dict(asset_id=assetid,definition_id=state.mt.parent['workflow_id'],definition_revision=1,options={'audio_goal':{'node_id':'transcription','options':{}}})
    with pytest.raises(LookupError): state.mt.handlers['preview'](state.mt.handlers['Selection'](**args),ACTOR)
    assert not state.runtime.database.children



def test_actual_mp3_registration_uses_content_and_preserves_literal_filename(registration):
    import subprocess
    state=registration;store=state.runtime.store
    source=store.root/'fixture-source.wav';source.write_bytes(state.raw)
    encoded=store.root/'fixture-only.mp3'
    subprocess.run([str(TOOLS/'ffmpeg.exe'),'-v','error','-i',str(source),'-c:a','libmp3lame','-b:a','64k',str(encoded)],check=True,capture_output=True,timeout=10)
    raw=encoded.read_bytes();part=store.put(OWNER,[raw],'upload_part')
    state.row.update(filename='literal source name.WAV',expected_size=len(raw),uploaded_bytes=len(raw))
    state.runtime._parts=lambda *a:[part];state.runtime._blocks=lambda *a:[raw]
    state.runtime.upload_complete(OWNER,state.row['id'])
    asset=state.assets[0]
    assert asset['filename']=='literal source name.WAV'
    assert asset['metadata']['media_type']=='audio/mpeg' and asset['metadata']['media']['codec']=='mp3'
    assert asset['sha256']==hashlib.sha256(raw).hexdigest() and asset['bytes']==len(raw)



def restore_runtime(mode):
    """Actual restore/save/upgrade/validation; synthetic revision SQL + registry only."""
    from mideagent_orchestrator.workflow import default_definition, selected_definition, compile_definition
    from video_service.canonical import digest
    from video_service.renewal_contracts import validate

    old = default_definition('literal audio history')
    old['nodes'][0].update(model_ref=deepcopy(PRIMARY), fallback_refs=[deepcopy(FALLBACK)])
    old['nodes'][0]['options'].update(source_language='ja', llm_options=LLM)
    old['nodes'][0]['tool_settings'] = {'transcribe': {
        'max_model_calls': '4', 'batch_policy': 'bounded_60s_v1',
        'clock_policy': 'packed_projection_v5', 'media_budget': 'audio_long_v5'}}
    if mode == 'audio':
        old = selected_definition(old, {'audio_goal': {'node_id': 'transcription', 'options': {}}})
    elif mode == 'selected_wav':
        old['inputs'] = {'audio': 'audio'}
        old['nodes'][0]['options']['audio_source'] = 'selected_audio'
    old.update(id='e' * 32, revision=2, executable=False)
    assert validate(old)['valid']
    before = deepcopy(old)
    native = compile_definition(old)['definition']

    class Revisions:
        revision = 5
        def __init__(self):
            self.inserts = []
            self.bindings = []
        def connection(self): return nullcontext(self)
        def execute(self, sql, params):
            value = None
            if sql.startswith('INSERT INTO workflows('):
                assert params == (OWNER, old['id'])
            elif sql.startswith('SELECT revision,library_removed_at FROM workflows'):
                assert params == (OWNER, old['id'])
                value = {'revision': self.revision, 'library_removed_at': None}
            elif sql.startswith('INSERT INTO workflow_revisions('):
                self.inserts.append(deepcopy(params))
            elif sql.startswith('UPDATE workflows SET revision='):
                assert params[1:] == (OWNER, old['id'])
                self.revision = params[0]
            else:
                raise AssertionError('Unexpected synthetic restore SQL: ' + sql)
            return SimpleNamespace(fetchone=lambda: deepcopy(value))

    db = Revisions()
    def definition(owner, identity, revision):
        assert (owner, identity, revision) == (OWNER, old['id'], 2)
        return old  # Deliberately shared object: detect historical mutation.
    def bindings(connection, owner, payload, *, active):
        assert connection is db and owner == OWNER and active is False
        assert compile_definition(payload)['definition']['nodes'] == native['nodes']
        db.bindings.append(deepcopy(payload))
    ns = intake_methods({'restore_definition', 'save_definition'})
    ns['validate'] = validate
    runtime = SimpleNamespace(database=db, definition=definition, _bindings=bindings)
    runtime.save_definition = MethodType(ns['save_definition'], runtime)
    runtime.restore_definition = MethodType(ns['restore_definition'], runtime)
    return SimpleNamespace(runtime=runtime, db=db, old=old, before=before, native=native, digest=digest)


@pytest.mark.parametrize('mode', ['audio', 'video', 'selected_wav'])
def test_audio_revision_restore_preserves_profile_and_new_revision_provenance(mode):
    state = restore_runtime(mode)
    result = state.runtime.restore_definition(OWNER, state.old['id'], 5, 2)
    assert result['revision'] == 6 and state.db.revision == 6
    assert result['id'] == state.old['id'] and result['executable'] is False
    assert len(state.db.inserts) == 1 and len(state.db.bindings) == 1
    inserted = state.db.inserts[0]
    assert inserted[:4] == (OWNER, state.old['id'], 6, state.old['name'])
    assert inserted[4] == result and inserted[5] == state.digest(result)
    assert inserted[6] == {'kind': 'definition_revision', 'revision': 2, 'sha256': state.digest(state.before)}
    assert result['inputs'] == state.before['inputs'] and result['nodes'] == state.before['nodes']
    assert result['edges'] == state.before['edges'] and result['catalog_version'] == 2
    if mode == 'audio':
        assert result['input_profile'] == 'audio_file_v1'
    else:
        assert 'input_profile' not in result and 'input_profile' not in state.db.bindings[0]
    assert state.old == state.before  # No old revision/model/options/input rewrite.


def test_audio_revision_restore_keeps_current_revision_cas_guard():
    state = restore_runtime('audio')
    with pytest.raises(ValueError, match='워크플로우가 변경됐습니다'):
        state.runtime.restore_definition(OWNER, state.old['id'], 4, 2)
    assert state.db.revision == 5 and not state.db.inserts and not state.db.bindings
    assert state.old == state.before
