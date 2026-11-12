"""Photo-input only: synthetic nonpersonal images, real source + fake SQL/CAS."""
import json
import struct
import subprocess
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace, MethodType, ModuleType
from contextlib import nullcontext, contextmanager
import sys
import hashlib
import pytest
from test_audio_original_input import ROOT, TOOLS, OWNER, ACTOR, store, registration, intake_methods, mt, state, connected, recovery_runtime, source_execution


def png(width=8, height=4):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0)) + chunk(b'IDAT',zlib.compress((b'\0'+b'\x20\x80\xc0'*width)*height)) + chunk(b'IEND',b'')


@pytest.fixture(params=['png','jpeg'])
def photo(request, store):
    path=store.root/'nonpersonal-pattern.png'; path.write_bytes(png())
    if request.param=='jpeg':
        target=store.root/'nonpersonal-pattern.jpg'
        subprocess.run([str(TOOLS/'ffmpeg.exe'),'-v','error','-i',str(path),'-frames:v','1','-q:v','3',str(target)],check=True,capture_output=True,timeout=10)
        path=target
    return path


def test_photo_real_registration_preserves_raw_bytes_and_no_video_derivatives(photo, registration):
    from mideagent_media_tools.operations import probe_original
    media=probe_original(photo)
    from video_service.image_original import probe as photo_probe
    assert photo_probe(str(photo))==media
    assert media['kind']=='image' and (media['width'],media['height'])==(8,4)
    assert media['orientation']==1 and 'duration' not in media
    fixture=registration; raw=photo.read_bytes(); part=fixture.runtime.store.put(OWNER,[raw],'upload_part')
    fixture.row.update(filename='literal source name.bin',expected_size=len(raw),uploaded_bytes=len(raw))
    fixture.runtime._parts=lambda *a:[part]; fixture.runtime._blocks=lambda *a:[raw]
    fixture.runtime.upload_complete(OWNER,fixture.row['id'])
    asset=fixture.assets[0]
    assert asset['sha256']==hashlib.sha256(raw).hexdigest() and asset['bytes']==len(raw)
    assert asset['filename']=='literal source name.bin'
    assert fixture.ns['asset_reference'](asset)['type']=='image'
    public=fixture.ns['public_asset'](asset)
    assert public['media_kind']=='image' and public['uploaded_by']==OWNER
    assert public['media']==media and 'duration' not in public['media']
    assert 'web_preview' not in public and 'thumbnail' not in asset['metadata']
    assert fixture.runtime.store.read(OWNER,fixture.ns['asset_reference'](asset))==raw
    (fixture.runtime.store.root/'photo-fixture-evidence.json').write_text(json.dumps({'synthetic_nonpersonal':True,'bytes':len(raw),'sha256':asset['sha256'],'media':media,'custodian':OWNER,'filename_preserved':asset['filename']},indent=2),encoding='utf8')



@pytest.fixture
def prepared(photo, registration, monkeypatch):
    # Production plan module must not import or execute any GPU/native path.
    from mideagent_orchestrator.face_inputs import FaceInputs
    from video_service.canonical import digest
    raw=photo.read_bytes();store=registration.runtime.store
    pref=store.put(OWNER,[raw],'image');vref=store.put('c'*32,[b'synthetic video bytes; no video decoding'],'video')
    from mideagent_media_tools.operations import probe_original
    from video_service.image_original import policy
    source=dict(owner_id=OWNER,id='d'*32,filename='unchanged source.jpg',storage_key='sha256:'+pref['sha256'],sha256=pref['sha256'],bytes=pref['bytes'],metadata={'registration_state':'verified','media':probe_original(photo),'media_type':'image/png' if photo.suffix=='.png' else 'image/jpeg','image_original_policy':policy()})
    target=dict(owner_id='c'*32,id='e'*32,filename='unchanged target.mp4',storage_key='sha256:'+vref['sha256'],sha256=vref['sha256'],bytes=vref['bytes'],metadata={'registration_state':'verified','media':{'duration':12,'width':640,'height':360,'has_audio':True}})
    descriptor=dict(role='faceswap',family='gpu',engine='facefusion-3.9.0',model_sha256='a'*64,source_language=None,target_language=None)
    engine=dict(role='faceswap',revision=3,sha256=digest(descriptor),descriptor=descriptor,enabled=True)
    class DB:
        depth=0
        @contextmanager
        def connection(self):
            self.depth+=1
            try: yield self
            finally: self.depth-=1
        def execute(self,query,params):
            if query.startswith('SELECT * FROM assets WHERE id='):
                return SimpleNamespace(fetchall=lambda:[deepcopy(assets[params[0]])] if params[0] in assets and not assets[params[0]].get('library_removed_at') else [])
            assert query.startswith('SELECT r.* FROM engine_runtime_heads') and 'FOR ' not in query
            return SimpleNamespace(fetchone=lambda:deepcopy(engine))
    db=DB();assets={source['id']:source,target['id']:target}
    ns=intake_methods({'_shared_asset','asset_reference'})
    # Existing metadata helper is loaded without PG package initializer.
    import ast
    engine_path=ROOT/'packages/shared/video_service/postgres/engine_runtimes.py'
    tree=ast.parse(engine_path.read_text(encoding='utf8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EngineRuntimes')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='resolve_in');method=deepcopy(method);method.decorator_list=[]
    from video_service.engine_protocol import validate_runtime
    env=dict(validate_runtime=validate_runtime,digest=digest)
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(engine_path),'exec'),env)
    module=ModuleType('video_service.postgres.engine_runtimes');module.EngineRuntimes=SimpleNamespace(resolve_in=env['resolve_in'])
    monkeypatch.setitem(sys.modules,module.__name__,module)
    runtime=SimpleNamespace(database=db,store=store,asset_reference=ns['asset_reference'])
    runtime._shared_asset=MethodType(ns['_shared_asset'],runtime)
    actual_path=store.path
    def unlocked_path(*args,**kwargs):
        assert db.depth==0, 'CAS read/decode inside metadata transaction'
        return actual_path(*args,**kwargs)
    monkeypatch.setattr(store,'path',unlocked_path)
    monkeypatch.setattr(store,'put',lambda *a,**k:pytest.fail('input plan staged CAS'))
    selections=dict(photo_asset_id=source['id'],target_asset_id=target['id'],engine_revision=3,engine_sha256=engine['sha256'],settings_revision=1,preset='fast',video_codec='h264')
    planner=FaceInputs(runtime)
    return SimpleNamespace(planner=planner,runtime=runtime,selections=selections,source=source,target=target,engine=engine,pref=pref,vref=vref,descriptor=descriptor)


def test_face_input_plan_binds_separate_photo_video_custody_without_execution(prepared):
    case=prepared;planner=case.planner;selections=case.selections
    pref,vref,descriptor,engine=case.pref,case.vref,case.descriptor,case.engine
    plan=planner.inspect(ACTOR,selections)
    assert plan['input_ready'] is True and plan['execution_ready'] is False
    assert plan['execution_reasons'] and plan['token'] and not plan.get('job_id')
    assert plan['bindings']['photo']['custodian_id']==OWNER and plan['bindings']['target']['custodian_id']=='c'*32
    assert plan['bindings']['photo']['reference']==pref and plan['bindings']['target']['reference']==vref
    assert plan['bindings']['settings']=={'revision':1,'preset':'fast','video_codec':'h264'}
    assert plan['bindings']['engine']['descriptor']==descriptor
    assert planner.inspect(ACTOR,{**selections,'preset':'quality'})['token']!=plan['token']
    engine['revision']=4
    with pytest.raises(ValueError): planner.inspect(ACTOR,selections)



@pytest.mark.parametrize('bad',['pixel','bytes','orientation','animated','crc','multiple','truncated'])
def test_photo_limits_and_single_image_framing_before_decode(bad, store, monkeypatch):
    from video_service.image_original import probe, framing, validate_media
    path=store.root/'bounded.png';raw=png()
    if bad=='pixel':
        raw=png(1,1);raw=raw[:16]+struct.pack('>II',24_000_001,1)+raw[24:]
        raw=raw[:29]+struct.pack('>I',zlib.crc32(raw[12:29])&0xffffffff)+raw[33:]
    elif bad=='bytes':
        with pytest.raises(ValueError): validate_media(dict(kind='image',format='png',width=1,height=1,orientation=1),10*1024**2+1)
        return
    elif bad=='orientation':
        with pytest.raises(ValueError): validate_media(dict(kind='image',format='jpeg',width=1,height=1,orientation=9),100)
        return
    elif bad=='animated':
        data=struct.pack('>II',2,0);chunk=struct.pack('>I',len(data))+b'acTL'+data+struct.pack('>I',zlib.crc32(b'acTL'+data)&0xffffffff)
        raw=raw[:33]+chunk+raw[33:]
    elif bad=='crc': raw=raw[:-5]+b'XXXXX'
    elif bad=='multiple': raw+=png()
    else: raw=raw[:-8]
    path.write_bytes(raw)
    import mideagent_media_tools.operations as operations
    monkeypatch.setattr(operations,'process',lambda *a,**k:pytest.fail('invalid frame must fail before decoder'))
    with pytest.raises(ValueError): probe(path)


def test_photo_exif_orientation_is_validated_without_transposing_raw_bytes(store):
    from video_service.image_original import probe,orientation
    raw_png=store.root/'base.png';raw_png.write_bytes(png())
    jpg=store.root/'raw.jpg'
    subprocess.run([str(TOOLS/'ffmpeg.exe'),'-v','error','-i',str(raw_png),'-frames:v','1',str(jpg)],check=True,capture_output=True,timeout=10)
    tiff=b'II'+struct.pack('<HIH',42,8,1)+struct.pack('<HHI',274,3,1)+struct.pack('<H',6)+b'\0\0'+b'\0'*4
    assert orientation(tiff)==6
    exif=b'Exif\0\0'+tiff;segment=b'\xff\xe1'+struct.pack('>H',len(exif)+2)+exif
    raw=jpg.read_bytes();raw=raw[:2]+segment+raw[2:];jpg.write_bytes(raw)
    before=hashlib.sha256(raw).hexdigest();media=probe(jpg)
    assert media==dict(kind='image',format='jpeg',width=8,height=4,orientation=6)
    assert hashlib.sha256(jpg.read_bytes()).hexdigest()==before
    with pytest.raises(ValueError): orientation(tiff[:-6])


@pytest.mark.parametrize('change',['photo_removed','unknown','target_duration','target_resolution','engine_disabled','foreign_pin','settings_extra'])
def test_face_inputs_reject_changed_or_unsupported_context(prepared,change):
    c=prepared;selected=deepcopy(c.selections)
    if change=='photo_removed': c.source['library_removed_at']='synthetic deletion'
    elif change=='unknown': selected['photo_asset_id']='f'*32
    elif change=='target_duration': c.target['metadata']['media']['duration']=31
    elif change=='target_resolution': c.target['metadata']['media']['width']=1281
    elif change=='engine_disabled': c.engine['enabled']=False
    elif change=='foreign_pin': selected['engine_sha256']='f'*64
    else: selected['mask_types']=['face']
    with pytest.raises((ValueError,LookupError)): c.planner.inspect(ACTOR,selected)


def test_face_inputs_missing_engine_is_not_execution_or_empty_success(prepared):
    c=prepared;c.engine['enabled']=False
    choices=c.planner.choices()
    assert choices['engines']==[] and choices['reason'] and choices['execution_ready'] is False
    result=c.planner.inspect(ACTOR,{**c.selections,'engine_revision':None,'engine_sha256':None})
    assert result['input_ready'] is False and result['input_reasons'] and result['execution_ready'] is False


def test_face_inputs_metadata_reread_rejects_change_during_io(prepared,monkeypatch):
    c=prepared;actual=c.runtime.store.path
    # Each snapshot must differ, not merely compare two already changed reads.
    count={'n':0}
    def unstable(*args,**kwargs):
        count['n']+=1;c.source['filename']='changed '+str(count['n']);return actual(*args,**kwargs)
    monkeypatch.setattr(c.runtime.store,'path',unstable)
    with pytest.raises(ValueError,match='변경'): c.planner.inspect(ACTOR,c.selections)


def test_native_nested_photo_origin_and_public_goal_stay_closed(prepared):
    from video_service.engine_protocol import reference
    from mideagent_orchestrator.workflow import compile_definition,default_definition
    with pytest.raises(ValueError): reference({**prepared.pref,'source_owner_id':OWNER})
    # No invented public face agent/preview acceptance is added by preparation.
    public=default_definition();public['nodes'][0]['type']='faceswap'
    with pytest.raises(ValueError): compile_definition(public)
    assert prepared.planner.inspect(ACTOR,prepared.selections)['execution_ready'] is False



def test_photo_corrupt_pixels_are_actually_decoded_and_rejected(store):
    from video_service.image_original import probe
    raw=png();start=raw.index(b'IDAT');end=start+4+struct.unpack_from('>I',raw,start-4)[0]
    body=b'not compressed pixels'
    chunk=struct.pack('>I',len(body))+b'IDAT'+body+struct.pack('>I',zlib.crc32(b'IDAT'+body)&0xffffffff)
    path=store.root/'corrupt-pixels.png';path.write_bytes(raw[:start-4]+chunk+raw[end+4:])
    with pytest.raises(ValueError): probe(path)


def face_app(runtime):
    """Production session/CSRF/origin/body middleware, ASGI only, no listener."""
    import ast, importlib.util, hmac, re
    from fastapi import FastAPI,Depends,HTTPException,Request
    from fastapi.responses import JSONResponse
    from video_service.admission_policy import AdmissionPolicy
    app=FastAPI()
    tree=ast.parse((ROOT/'apps/api/app/renewal.py').read_text(encoding='utf8'))
    names={'session','request_boundary','JsonBodyLimit'}
    nodes=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
    ns=dict(app=app,Request=Request,HTTPException=HTTPException,JSONResponse=JSONResponse,hmac=hmac,re=re,
            accounts=SimpleNamespace(session=lambda token:{'user':{'id':ACTOR,'role':'user'},'csrf_token':'csrf'} if token=='valid' else None),
            cookie='unit_session',origins={'https://face.invalid'},content_store=runtime.store,policy=AdmissionPolicy())
    for node in nodes: exec(compile(ast.Module(body=[node],type_ignores=[]),'renewal.py','exec'),ns)
    app.add_middleware(ns['JsonBodyLimit'],uploads=True)
    def owner(actor=Depends(ns['session'])): return actor['user']['id']
    path=ROOT/'apps/api/app/face_input_routes.py';spec=importlib.util.spec_from_file_location('face_input_route_unit',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.mount_face_inputs(app,runtime,Depends(owner))
    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({'detail':str(exc)},status_code=422)
    return app


def call_face(app,body=None,*,cookie='valid',csrf='csrf',origin='https://face.invalid',path=None):
    import asyncio
    async def invoke():
        messages=[];pending=[dict(type='http.request',body=json.dumps(body).encode() if body is not None else b'',more_body=False)]
        async def receive():
            if pending:return pending.pop()
            await asyncio.Event().wait()
        async def send(message):messages.append(message)
        route=path or ('/api/work-entry/faceswap-inputs/inspect' if body is not None else '/api/work-entry/faceswap-inputs')
        await app(dict(type='http',http_version='1.1',method='POST' if body is not None else 'GET',scheme='https',path=route,raw_path=route.encode(),query_string=b'',headers=[(b'host',b'face.invalid'),(b'content-type',b'application/json'),(b'origin',origin.encode()),(b'cookie',('unit_session='+cookie).encode()),(b'x-csrf-token',csrf.encode())],client=('unit',1),server=('face.invalid',443),root_path=''),receive,send)
        return messages[0]['status'],json.loads(b''.join(m.get('body',b'') for m in messages))
    return asyncio.run(invoke())


def test_actual_face_routes_auth_csrf_origin_strict_body_and_read_only_plan(prepared):
    c=prepared;app=face_app(c.runtime)
    status,choices=call_face(app)
    assert status==200 and choices['engines'][0]['revision']==3 and choices['execution_ready'] is False
    assert call_face(app,c.selections,cookie='bad')[0]==401
    assert call_face(app,c.selections,csrf='bad')[0]==403
    assert call_face(app,c.selections,origin='https://foreign.invalid')[0]==403
    assert call_face(app,{**c.selections,'approved':True})[0]==422
    assert call_face(app,{**c.selections,'source_owner_id':ACTOR})[0]==422
    status,result=call_face(app,c.selections)
    assert status==200 and result['input_ready'] is True and result['execution_ready'] is False
    assert 'bindings' not in result and 'storage_key' not in json.dumps(result)
    assert call_face(app,c.selections,path='/api/work-entry/faceswap-inputs/start')[0]==404


def test_actual_create_rejects_preparation_as_job_or_photo_target(prepared,mt):
    from test_saved_subtitle_translation import options as mt_options
    c=prepared;runtime=mt.runtime
    runtime.store=c.runtime.store
    runtime._shared_asset=lambda db,id:deepcopy(c.source if id==c.source['id'] else c.target)
    runtime.asset_reference=c.runtime.asset_reference
    with pytest.raises(ValueError,match='작업 옵션'):
        runtime.create(ACTOR,c.target['id'],mt.parent['workflow_id'],1,options={'faceswap_inputs':'1'*64},request_id='offline-face-create-refused')
    with pytest.raises(ValueError,match='사진은'):
        runtime.create(ACTOR,c.source['id'],mt.parent['workflow_id'],1,options=mt_options(),request_id='offline-photo-target-refused')
    assert not runtime.database.children


def test_actual_plan_type_guard_and_checked_input_reject_photo_as_video(prepared,mt):
    # Existing valid MT-only synthetic draft is a positive control for shared
    # _plan input/type/custody validation, not an MT acceptance journey.
    from test_saved_subtitle_translation import options as mt_options
    from video_service.canonical import digest
    c=prepared;runtime=mt.runtime
    # Keep the fixture's saved-copy CAS while adding actual photo bytes to it.
    old_path=runtime.store.path
    def path(owner,ref,*args,**kwargs):
        if ref.get('type')=='image': return c.runtime.store.path(owner,ref)
        return old_path(owner,ref,*args,**kwargs)
    runtime.store.path=path
    job=runtime.create(ACTOR,'d'*32,mt.parent['workflow_id'],1,options=mt_options(),request_id='offline-type-control',paid_confirmed=True)
    job['revision']=1;runtime.database.jobs[job['id']]=job
    verified=runtime._preflight_cpu_inputs(ACTOR,job['id'])
    positive=runtime._plan(runtime.database,job,verified)
    assert positive['ready'], positive['reasons']
    job['snapshot']['inputs']['video']={**c.pref,'source_owner_id':OWNER}
    job['snapshot_sha256']=digest(job['snapshot'])
    with pytest.raises(ValueError):runtime._checked_input(ACTOR,job,job['snapshot']['inputs']['video'],verified)
    fresh=runtime._preflight_cpu_inputs(ACTOR,job['id'])
    assert not runtime._plan(runtime.database,job,fresh)['ready']



def test_face_route_storage_forbidden_is_not_healthy_or_empty(prepared,monkeypatch):
    from video_service.object_store import ObjectStoreError
    app=face_app(prepared.runtime)
    def forbidden(*args,**kwargs): raise ObjectStoreError('synthetic denial',status=403,code='AccessDenied')
    monkeypatch.setattr(prepared.runtime.store,'path',forbidden)
    status,result=call_face(app,prepared.selections)
    assert status==403 and 'input_ready' not in result and '저장소' in result['detail']



def test_photo_compressed_metadata_bomb_rejected_before_decoder(store,monkeypatch):
    from video_service.image_original import probe
    raw=png();body=b'profile\0\0'+zlib.compress(b'A'*(5*1024**2))
    chunk=struct.pack('>I',len(body))+b'iCCP'+body+struct.pack('>I',zlib.crc32(b'iCCP'+body)&0xffffffff)
    path=store.root/'metadata-bomb.png';path.write_bytes(raw[:33]+chunk+raw[33:])
    import mideagent_media_tools.operations as operations
    monkeypatch.setattr(operations,'process',lambda *a,**k:pytest.fail('compressed metadata reached decoder'))
    with pytest.raises(ValueError):probe(path)



def test_compressed_itxt_oversized_prefix_rejected_before_decoder(store,monkeypatch):
    from video_service.image_original import probe, MAX_METADATA, MAX_BYTES
    # Valid CRC / zlib / UTF-8 iTXt with a large translated keyword, tiny text.
    prefix=b'comment\0\x01\0ko\0'+b'K'*(MAX_METADATA+1)+b'\0'
    body=prefix+zlib.compress(b'ok')
    chunk=struct.pack('>I',len(body))+b'iTXt'+body+struct.pack('>I',zlib.crc32(b'iTXt'+body)&0xffffffff)
    raw=png();raw=raw[:33]+chunk+raw[33:]
    assert len(raw)<=MAX_BYTES and len(prefix)>MAX_METADATA
    path=store.root/'oversized-itxt-prefix.png';path.write_bytes(raw)
    import mideagent_media_tools.operations as operations
    monkeypatch.setattr(operations,'process',lambda *a,**k:pytest.fail('oversized uncompressed prefix reached decoder'))
    with pytest.raises(ValueError):probe(path)


@pytest.mark.parametrize('kind,prefix',[
    (b'iCCP',b'profile\0\0'),
    (b'zTXt',b'comment\0\0'),
    (b'iTXt',b'comment\0\x01\0ko\0translated\0'),
])
def test_compressed_metadata_prefix_plus_text_and_cumulative_budget(kind,prefix,monkeypatch):
    import video_service.image_original as image
    text=b'small valid text';body=prefix+zlib.compress(text)
    total=len(prefix)+len(text)
    assert image.metadata_size(kind,body,total)==total
    assert image.metadata_size(kind,body,total+1)==total
    with pytest.raises(ValueError):image.metadata_size(kind,body,total-1)
    # Reduced unit budget exercises real framing's cumulative accounting.
    monkeypatch.setattr(image,'MAX_METADATA',128)
    def chunk(tag,data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    raw=png();first=chunk(kind,body)
    exact=b'pad\0'+b'x'*(128-total-4)
    assert image.framing(raw[:33]+first+chunk(b'tEXt',exact)+raw[33:])['kind']=='image'
    with pytest.raises(ValueError):image.framing(raw[:33]+first+chunk(b'tEXt',exact+b'x')+raw[33:])
    # An over-budget prefix must fail even before starting zlib expansion.
    monkeypatch.setattr(image.zlib,'decompressobj',lambda:pytest.fail('prefix exceeded remaining before zlib'))
    with pytest.raises(ValueError):image.metadata_size(kind,body,len(prefix)-1)
