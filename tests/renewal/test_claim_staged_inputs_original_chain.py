"""Original audio must not masquerade as a normalized successor output."""
from copy import deepcopy
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from test_claim_staged_inputs import admin, db, movie, ByteCountedS3
from test_claim_cold_gate import counts
from test_execution import admit
from test_model_role_orchestration import formal
from video_service.object_store import S3ContentStore


def test_numeric_transcription_rejects_original_stereo_reused_as_normalized_output(db,admin,movie,tmp_path):
    from test_audio_original_input import pcm
    from mideagent_orchestrator.workflow import default_definition,selected_definition
    client=ByteCountedS3()
    runtime,owner,legacy=formal(db,admin,movie,tmp_path,store=S3ContentStore(client,'synthetic-origin',tmp_path,prefix='origin'),prepare=False)
    source=default_definition()
    source['nodes'][0]['model_ref']=next(n['model_ref'] for n in legacy['snapshot']['definition']['nodes'] if n['type']=='transcribe')
    chosen=selected_definition(source,{'audio_goal':{'node_id':'transcription','options':{'source_language':'en'}}})
    chosen['nodes'][0].setdefault('tool_settings',{}).setdefault('transcribe',{})['max_model_calls']='3'
    saved=runtime.save_definition(owner,uuid4().hex,chosen)
    asset=runtime.ingest(owner,'stereo.wav',pcm())
    job=runtime.create(owner,asset['asset_id'],saved['id'],saved['revision'],request_id=uuid4().hex,options={'source_language':'en','target_language':'ko'})
    admit(runtime,owner,job['id'])
    preparation=runtime.claim_next(owner,job['id'])
    assert preparation['agent']['id']=='preprocess_audio'
    result=runtime.execute_command(owner,preparation)
    assert result['status']=='completed'
    runtime.accept(owner,preparation,result)
    with db.connection() as conn:
        row=runtime._runs(conn,owner,job['id'])[0]
        invalid=deepcopy(row['result'])
        invalid['outputs']['audio']=job['snapshot']['inputs']['audio']
        conn.execute('UPDATE node_runs SET result=%s WHERE id=%s',(Jsonb(invalid),row['id']))
    before=counts(db,job)
    # Byte-identical broad base validator rejects this same malformed frontier.
    with pytest.raises(ValueError,match='bounded_pcm'):
        runtime._preflight_cpu_inputs(owner,job['id'])
    with pytest.raises(ValueError,match='bounded_pcm'):
        runtime.claim_next(owner,job['id'])
    assert counts(db,job)==before
