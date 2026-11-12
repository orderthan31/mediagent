"""M4A-only additions: real tiny AAC fixture + production paths, fake SQL/registry."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from test_audio_original_input import (
    ROOT, TOOLS, OWNER, ACTOR, PRIMARY, FALLBACK, LLM, pcm, intake_methods,
    store, registration, audio_runtime, mt, state, connected, recovery_runtime, source_execution,
)


@pytest.fixture
def m4a(store):
    wav = store.root / 'generated-sine.wav'
    wav.write_bytes(pcm())
    path = store.root / 'generated.m4a'
    subprocess.run([str(TOOLS / 'ffmpeg.exe'), '-v', 'error', '-i', str(wav),
                    '-c:a', 'aac', '-b:a', '64k', '-f', 'ipod', str(path)],
                   check=True, capture_output=True, timeout=10)
    raw_probe = json.loads(subprocess.run([
        str(TOOLS / 'ffprobe.exe'), '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(path)], check=True, capture_output=True, timeout=10).stdout)
    assert raw_probe['format']['format_name'] == 'mov,mp4,m4a,3gp,3g2,mj2'
    assert raw_probe['format']['tags']['major_brand'] == 'M4A '
    assert len(raw_probe['streams']) == 1 and raw_probe['streams'][0]['codec_name'] == 'aac'
    evidence = {'synthetic': True, 'raw_probe': raw_probe, 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (store.root / 'm4a-fixture-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')
    return path


def test_m4a_real_probe_registration_and_revalidation(m4a, registration):
    from mideagent_media_tools.operations import probe_original
    from video_service.audio_original import asset_media, policy
    media = probe_original(m4a)
    assert media == dict(kind='audio', format='m4a', codec='aac', duration=.2, sample_rate=44100, channels=2)
    raw = m4a.read_bytes()
    fixture = registration
    part = fixture.runtime.store.put(OWNER, [raw], 'upload_part')
    fixture.row.update(filename='literal untrusted name.WAV', expected_size=len(raw), uploaded_bytes=len(raw))
    fixture.runtime._parts = lambda *a: [part]
    fixture.runtime._blocks = lambda *a: [raw]
    result = fixture.runtime.upload_complete(OWNER, fixture.row['id'])
    assert result['asset_id'] and len(fixture.assets) == 1
    asset = fixture.assets[0]
    assert asset['filename'] == 'literal untrusted name.WAV'
    assert asset['metadata']['media_type'] == 'audio/mp4' and asset_media(asset) == media
    assert asset['metadata']['audio_original_policy'] == policy()
    assert asset['sha256'] == hashlib.sha256(raw).hexdigest() and asset['bytes'] == len(raw)
    assert fixture.ns['asset_reference'](asset)['type'] == 'audio'
    public = fixture.ns['public_asset'](asset)
    assert public['media_kind'] == 'audio' and public['media_type'] == 'audio/mp4'
    assert public['uploaded_by'] == OWNER and 'web_preview' not in public
    assert 'thumbnail' not in asset['metadata'] and 'width' not in media
    wrong = deepcopy(asset); wrong['metadata']['media_type'] = 'audio/mpeg'
    with pytest.raises(ValueError): asset_media(wrong)



def metadata():
    # Pure metadata unit fixture; real probe/codec evidence is tested separately.
    return {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '1',
                       'tags': {'major_brand': 'M4A '}},
            'streams': [{'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '44100', 'channels': 2}]}


@pytest.mark.parametrize('change', ['alias', 'raw_aac', 'flac', 'alac', 'brand', 'trimmed_brand', 'missing_brand', 'missing_codec', 'multiple', 'video'])
def test_m4a_metadata_rejects_unproven_container_codec_and_streams(change):
    from video_service.audio_original import classify
    info = metadata()
    if change == 'alias': info['format']['format_name'] = 'm4a'
    elif change == 'raw_aac': info['format']['format_name'] = 'aac'
    elif change == 'flac': info['format']['format_name'] = 'flac'; info['streams'][0]['codec_name'] = 'flac'
    elif change == 'alac': info['streams'][0]['codec_name'] = 'alac'
    elif change == 'brand': info['format']['tags']['major_brand'] = 'isom'
    elif change == 'trimmed_brand': info['format']['tags']['major_brand'] = 'M4A'
    elif change == 'missing_brand': info['format'].pop('tags')
    elif change == 'missing_codec': info['streams'][0].pop('codec_name')
    elif change == 'multiple': info['streams'].append(deepcopy(info['streams'][0]))
    else: info['streams'].append({'codec_type': 'video', 'disposition': {'attached_pic': 0}})
    with pytest.raises(ValueError): classify(info, 100)


def test_m4a_cover_allowed_but_real_video_routes_to_unchanged_video_probe(tmp_path, monkeypatch):
    from video_service.audio_original import classify
    from mideagent_media_tools import operations
    info = metadata()
    info['streams'].append({'codec_type': 'video', 'disposition': {'attached_pic': 1}})
    assert classify(info, 100)['format'] == 'm4a'
    info['streams'][-1].update(width=32, height=32, r_frame_rate='25/1', disposition={'attached_pic': 0})
    path = tmp_path / 'ordinary-video.m4a'; path.write_bytes(b'only metadata routing unit fixture')
    calls = []
    def process(args, **kwargs):
        calls.append(args)
        assert args[args.index('-protocol_whitelist') + 1] == 'file,pipe'
        assert args[args.index('-format_whitelist') + 1] == 'mov,matroska,webm,wav,mp3,ogg'
        assert kwargs == {'timeout': 10}
        return json.dumps(info).encode()
    monkeypatch.setattr(operations, 'process', process)
    video = operations.probe_original(path)
    assert video == dict(duration=1., width=32, height=32, has_audio=True, frame_rate='25/1')
    assert len(calls) == 2  # Actual probe_original -> existing probe, metadata stub only.
    assert 'format_tags=major_brand' in calls[0][calls[0].index('-show_entries') + 1]


@pytest.mark.parametrize('field,value', [('sample_rate', 96000), ('channels', 3), ('channels', True), ('duration', float('nan')), ('duration', 21601), ('duration', 0)])
def test_m4a_bounded_canonical_media(field, value):
    from video_service.audio_original import classify, validate_media, MAX_BYTES
    media = classify(metadata(), 100)
    with pytest.raises(ValueError): validate_media(media, MAX_BYTES + 1)
    media[field] = value
    with pytest.raises(ValueError): validate_media(media, 100)


def test_m4a_bounds_and_existing_policy_values_remain():
    from video_service.audio_original import classify, validate_media, policy, ID, PROFILE, MAX_BYTES
    media = classify(metadata(), MAX_BYTES)
    for rate in (8000, 48000):
        assert validate_media({**media, 'sample_rate': rate, 'channels': 1, 'duration': 21600}, MAX_BYTES)
    assert policy() == {'id': 'original_audio_v1', 'max_source_bytes': 256*1024**2,
                        'max_source_seconds': 21600, 'normalized_max_bytes': 1024**3}
    assert (ID, PROFILE) == ('original_audio_v1', 'audio_file_v1')
    for format, codec in [('wav', 'pcm_s16le'), ('mp3', 'mp3')]:
        info = metadata(); info['format']['format_name'] = format; info['format'].pop('tags'); info['streams'][0]['codec_name'] = codec
        assert classify(info, 100) == {**media, 'format': format, 'codec': codec}


def test_m4a_filename_cannot_make_actual_raw_adts_audio_valid(m4a, store):
    from mideagent_media_tools.operations import probe_original
    raw = store.root / 'false-extension.m4a'
    subprocess.run([str(TOOLS/'ffmpeg.exe'), '-v', 'error', '-i', str(m4a), '-c:a', 'copy', '-f', 'adts', str(raw)], check=True, capture_output=True, timeout=10)
    with pytest.raises(ValueError): probe_original(raw)


@pytest.mark.parametrize('audio_runtime', [{'container': 'm4a', 'max_calls': 1}], indirect=True)
def test_m4a_real_create_plan_claim_normalization_and_role_envelope(audio_runtime, tmp_path, monkeypatch):
    """No operating job: real source methods + temp CAS, fake SQL/grants/registry."""
    import ast
    import wave
    from mideagent_media_tools import operations
    from video_service.canonical import digest
    from video_service.long_audio_budget import read_clock
    from video_service.packed_projection import validate_projection_clock
    from video_service.role_task_contracts import validate
    fixture = audio_runtime; runtime = fixture.runtime; handlers = fixture.mt.handlers
    source_before = deepcopy(fixture.asset)
    args = dict(asset_id=fixture.asset['id'], definition_id=fixture.mt.parent['workflow_id'], definition_revision=1,
                options={'audio_goal': {'node_id': 'transcription', 'options': {}}})
    with monkeypatch.context() as read_only:
        read_only.setattr(runtime.store, 'put', lambda *a, **k: pytest.fail('preview wrote CAS'))
        preview = handlers['preview'](handlers['Selection'](**args), ACTOR)
    assert preview['model_call_budgets'][0]['max_calls'] == 1 and not runtime.database.children
    job = handlers['create'](handlers['Create'](**args, token=preview['token'], request_id='offline-m4a-only', paid_confirmed=True), ACTOR)
    job['revision'] = 1; runtime.database.jobs[job['id']] = job
    snapshot = job['snapshot']
    assert job['asset_id'] == fixture.asset['id'] and job['workflow_owner_id'] == OWNER
    assert snapshot['asset']['uploaded_by'] == fixture.owner
    assert snapshot['agent_definition']['input_profile'] == 'audio_file_v1'
    assert [n['type'] for n in snapshot['definition']['nodes']] == ['preprocess_audio', 'transcribe']
    assert snapshot['inputs'] == {'audio': {**fixture.ref, 'source_owner_id': fixture.owner}}
    verified = runtime._preflight_cpu_inputs(ACTOR, job['id'])
    runtime._checked_input(ACTOR, job, snapshot['inputs']['audio'], verified)
    assert runtime._plan(runtime.database, job, verified)['ready']
    job.update(status='waiting', active_claim_id='6'*32)  # Synthetic grant only.
    command = runtime.claim_next(ACTOR, job['id'])
    assert command['agent'] == {'id': 'preprocess_audio', 'revision': '5'}
    normalize_calls = []; actual = operations.process_bounded
    def bounded(arguments, **kwargs):
        normalize_calls.append(arguments)
        return actual(arguments, **kwargs)  # Real local AAC decode, never a fake success.
    monkeypatch.setattr(operations, 'process_bounded', bounded)
    output = tmp_path / 'isolated-aac-normalized'; output.mkdir()
    result = operations.run(command, runtime.store.owner_root(ACTOR), output)
    assert result['status'] == 'completed', result
    normalize = next(a for a in normalize_calls if '-c:a' in a and a[a.index('-c:a')+1] == 'pcm_s16le')
    assert Path(normalize[normalize.index('-i')+1]).suffix == '.media'
    assert '-vn' in normalize and normalize[normalize.index('-ac')+1] == '1' and normalize[normalize.index('-ar')+1] == '16000'
    refs = {port: runtime.store.put(ACTOR, [(output/ref['storage_key']).read_bytes()], ref['type'], max_bytes=1024**3) for port, ref in result['outputs'].items()}
    clock = json.loads(runtime.store.read(ACTOR, refs['timeline']))
    assert clock['source_sha256'] == fixture.ref['sha256'] and clock['audio_sha256'] == refs['audio']['sha256']
    assert clock['source_frames'] > 0 and clock['source_frames'] != len(fixture.raw)
    with wave.open(str(runtime.store.path(ACTOR, refs['audio'])), 'rb') as wav:
        pcm_info = {'channels': wav.getnchannels(), 'sample_rate': wav.getframerate(), 'sample_width': wav.getsampwidth(), 'frames': wav.getnframes()}
    assert (pcm_info['channels'], pcm_info['sample_rate'], pcm_info['sample_width']) == (1, 16000, 2)
    runtime.database.runs[job['id']][0].update(status='completed', result={'status': 'completed', 'outputs': refs})
    asr = runtime.claim_next(ACTOR, job['id'])
    assert asr['agent']['id'] == 'transcribe' and asr['inputs'] == refs
    assert asr['transcription']['max_model_calls'] == 1 and asr['transcription']['source_language'] == 'ja'
    assert json.loads(asr['options']['llm_options']) == json.loads(LLM)
    pins = asr['transcription']['candidates']
    assert [(p['model_id'],p['revision']) for p in pins] == [(PRIMARY['model_id'],PRIMARY['revision']), (FALLBACK['model_id'],FALLBACK['revision'])]
    assert all(p['owner_id'] == OWNER for p in pins)
    path = ROOT / 'packages/shared/video_service/postgres/model_roles.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf8')).body if isinstance(n,ast.ClassDef) and n.name == 'ModelRoles')
    methods = [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_policy_version','_current','enroll','_model_binding'}]
    ns = dict(__package__='video_service.postgres', deepcopy=deepcopy, json=json, digest=digest, Jsonb=lambda x:deepcopy(x), Conflict=ValueError, validate_projection_clock=validate_projection_clock)
    shell = ast.ClassDef(name='ModelRoles', bases=[], keywords=[], body=methods, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[shell],type_ignores=[])),str(path),'exec'),ns)
    roles=ns['ModelRoles'](); roles.runtime=runtime
    envelope=roles.enroll(ACTOR,asr); validate(envelope,'result',expected_role='transcription')
    assert envelope['task']['max_calls'] == 1 and envelope['task']['source_language'] == 'ja'
    assert envelope['task']['timeline'] == read_clock(clock,audio_sha256=refs['audio']['sha256'])
    assert envelope['task']['models'][0]['pin_sha256'] == digest(pins[0])
    assert envelope['source'] == {'owner': ACTOR, 'reference': refs['audio']}
    assert fixture.asset == source_before  # Original registration is unchanged.
    (tmp_path/'m4a-normalization-evidence.json').write_text(json.dumps({'synthetic': True,
        'source_bytes':len(fixture.raw),'source_sha256':fixture.ref['sha256'],'media':fixture.asset['metadata']['media'],
        'normalized_audio':refs['audio'],'clock':clock,'pcm':pcm_info,'max_calls':1},indent=2),encoding='utf8')
    # The same compressed source cannot masquerade as a normalized ASR receipt.
    runtime.database.runs[job['id']][0]['result']['outputs']['audio'] = snapshot['inputs']['audio']
    with pytest.raises((ValueError, wave.Error)): runtime._preflight_cpu_inputs(ACTOR,job['id'])
