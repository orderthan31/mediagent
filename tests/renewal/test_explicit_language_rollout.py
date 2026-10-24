"""Scoped rollout proof: one original, three explicitly pinned translation targets; no new review WIP."""
import json
import os
from uuid import uuid4

import httpx
from test_execution import admin as _admin,db as _db,movie as _movie,admit
from test_packed_projection_execution import projection_wire as _wire
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin,db,movie,projection_wire=_admin,_db,_movie,_wire


def test_explicit_targets_freeze_per_node_and_legacy_target_remains(db,admin,movie,tmp_path,projection_wire):
    owner=admin[0]['id'];origin,calls=projection_wire;credentials=CredentialStore(db,os.urandom(32));refs=[]
    for speech in [True,False]:
        cid,mid=uuid4().hex,uuid4().hex
        connection=Registry(db).save_connection(owner,cid,revision=0,name='controlled target proof',provider='openai_compatible',protocol='gemini',endpoint=origin+'/v1')
        connection=credentials.save(owner,cid,revision=connection['revision'],secret=uuid4().hex)
        Registry(db).save_model(owner,mid,revision=0,name='controlled targets',model='gemini-2.5-flash',connection_id=cid,connection_revision=connection['current_revision'],model_types=['speech_recognition'if speech else'text'],input_modalities=['audio'if speech else'text'],output_modalities=['text'],capabilities=['speech_recognition'if speech else'text_generation'])
        refs.append({'model_id':mid,'revision':1})
    kwargs={'transport_factory':lambda:httpx.HTTPTransport(retries=0),'approved_origins':{origin},'mode':'controlled_http'}
    runtime=Execution(db,ContentStore(tmp_path),translation_runtime=TranslationRuntime(credentials,**kwargs),transcription_runtime=TranscriptionRuntime(credentials,**kwargs))
    graph=audio_graph(*refs)
    for index,language in enumerate(['ja','fr'],1):
        name='language'+str(index)
        graph['nodes'].append({'id':name,'type':'translate','options':{'translation_profile':'language_target_v1','target_language':language,'batch_policy':'bounded_100x16k_v1','max_model_calls':'1'},'position':{'x':1200,'y':index*150},'model_ref':refs[1]})
        graph['edges'].append({'id':'languageedge'+str(index),'source':{'node':'asr','port':'transcript'},'target':{'node':name,'port':'transcript'}})
    definition=runtime.save_definition(owner,uuid4().hex,graph);asset=runtime.ingest(owner,'controlled-language-sample.mp4',movie)
    job=runtime.create(owner,asset['asset_id'],definition['id'],definition['revision'],request_id=uuid4().hex,options={'source_language':'en','target_language':'ko'})
    admit(runtime,owner,job['id']);done=runtime.run_local(owner,job['id']);assert done['status']=='completed',done
    targets={row['node_id']:row['result']['translation']['target_language']for row in done['runs']if row['node_type']=='translate'}
    assert targets=={'translate':'ko','language1':'ja','language2':'fr'}
    assert calls==['transcription']+['translation']*3
    for run in done['runs']:
        if run['node_type']=='translate':
            assert json.loads(runtime.store.read(owner,run['result']['outputs']['transcript']))[0]['text']=='전체 문장'
