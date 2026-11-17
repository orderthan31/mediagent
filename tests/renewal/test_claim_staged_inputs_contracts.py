"""Pure stage unit negatives over actual remote-verifying S3 and PCM parser."""
import io
import struct
import wave

import pytest

from test_claim_staged_inputs import ByteCountedS3
from video_service.canonical import canonical, digest
from video_service.object_store import S3ContentStore
from mideagent_orchestrator.execution import Execution

OWNER='a'*32


def material(tmp_path, *, long=False, frames=7, declared=None, truncate=False):
    client=ByteCountedS3()
    store=S3ContentStore(client,'synthetic-contracts',tmp_path,prefix='contracts')
    raw=io.BytesIO()
    with wave.open(raw,'wb') as stream:
        stream.setparams((1,2,16000,0,'NONE','not compressed'))
        stream.writeframes(b'\0'*(frames*2))
    content=bytearray(raw.getvalue())
    if declared is not None:
        content[40:44]=struct.pack('<I',declared*2)
    if truncate:
        content=content[:-1]
    reference=store.put(OWNER,[bytes(content)],'audio')
    node={'id':'prepare','type':'preprocess_audio','options':{'vad_mode':'off','audio_filter':'off'}}
    snapshot={'inputs':{},'definition':{'nodes':[node],'edges':[]},'options':{},'model_bindings':{}}
    if long:
        from video_service.long_audio_budget import policy
        snapshot['audio_pipeline_policy']=policy()
        node['options'].update(processing_profile='regions_long_v5',media_budget='audio_long_v5')
    job={'id':'b'*32,'owner_id':OWNER,'generation':1,'active_claim_id':'c'*32,'snapshot':snapshot,'snapshot_sha256':digest(snapshot)}
    candidate=canonical({'actor':OWNER,'job':job,'node':node,'inputs':{'audio':reference}})
    runtime=object.__new__(Execution)
    runtime.store=store
    # Exclude the seed put's mandatory verification GET from stage measurements.
    client.calls.clear()
    client.byte_reads.clear()
    return runtime,client,candidate,reference


@pytest.mark.parametrize('long,maximum',[(False,300),(True,21600)])
def test_exact_selected_pcm_bounds_and_full_frame_traversal(tmp_path,long,maximum):
    runtime,client,candidate,reference=material(tmp_path,long=long,declared=maximum*16000+1)
    with pytest.raises(ValueError,match='bounded_pcm'):
        runtime._stage_claim_candidate(candidate)
    assert len(client.byte_reads)==2


@pytest.mark.parametrize('long',[False,True])
def test_selected_truncated_pcm_is_not_header_only_validation(tmp_path,long):
    runtime,client,candidate,reference=material(tmp_path,long=long,truncate=True)
    with pytest.raises(ValueError,match='incomplete_audio_region_source'):
        runtime._stage_claim_candidate(candidate)
    assert len(client.byte_reads)==2


@pytest.mark.parametrize('long,kind',[(False,'audio_regions_v1'),(True,'audio_regions_long_v5')])
def test_exact_selected_frame_clock_contract_and_ordinary_repeated_reads(tmp_path,monkeypatch,long,kind):
    import video_service.postgres.audio_region_reviews as reviews
    runtime,client,candidate,reference=material(tmp_path,long=long)
    actual=reviews.contract_for
    observed=[]
    def contract(*args,**kwargs):
        result=actual(*args,**kwargs)
        observed.append(result)
        return result
    monkeypatch.setattr(reviews,'contract_for',contract)
    runtime._stage_claim_candidate(candidate)
    assert observed[0]['kind']==kind and observed[0]['source']==reference
    assert observed[0]['audio']=={'source_sha256':reference['sha256'],'source_frames':7,'sample_rate':16000,'duration_seconds':7/16000}
    assert len(client.byte_reads)==2
    assert all(size==reference['bytes'] for _,size in client.byte_reads)
