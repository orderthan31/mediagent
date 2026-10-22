"""Disposable loopback S3 emulator; no production objects or provider requests."""
from pathlib import Path
from uuid import uuid4

import pytest
from test_object_agents import objects as objects, command
from test_execution import movie as movie
from video_service.object_store import from_config, ObjectStoreError
from video_service.object_agent import ObjectAgentExecutor


def test_remote_shared_input_reads_original_key_without_copy(objects,tmp_path):
    store,config,_,env=objects
    uploader,actor=uuid4().hex,uuid4().hex
    ref=store.put(uploader,[b'synthetic original bytes'],'video')
    keys=lambda: {x['Key'] for x in store.client.list_objects_v2(Bucket=config['bucket']).get('Contents',[])}
    before=keys()
    cache=tmp_path/'reader';cache.mkdir()
    reader=from_config({**config,'cache_root':str(cache)},environ=env)
    assert reader.read(actor,{**ref,'source_owner_id':uploader})==b'synthetic original bytes'
    assert keys()==before
    assert not (reader.owner_root(actor)/ref['storage_key']).exists()
    with pytest.raises(ObjectStoreError):reader.path(actor,{**ref,'source_owner_id':'../escape'})


def test_independent_s3_worker_reads_a_origin_and_writes_b_outputs(objects,movie):
    store,config,agent_config,env=objects
    uploader,actor=uuid4().hex,uuid4().hex
    ref=store.put(uploader,[movie],'video')
    cmd=command({**ref,'source_owner_id':uploader})
    executor=ObjectAgentExecutor('SYNTHETIC_AGENT_CONFIG',environ=env)
    result=executor(actor,cmd)
    # Executor raises unless the independent JSON-line process really exits zero.
    assert result['status']=='completed' and result['transport']=='s3_subprocess',result
    output=result['outputs']['video']
    assert output['sha256']!=ref['sha256']
    assert store.path(actor,output).is_file()
    keys={x['Key'] for x in store.client.list_objects_v2(Bucket=config['bucket']).get('Contents',[])}
    assert store._key(uploader,ref['storage_key']) in keys
    assert store._key(actor,ref['storage_key']) not in keys
    assert store.read(uploader,ref)==movie
    assert executor(actor,cmd)==result
