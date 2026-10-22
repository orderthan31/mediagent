"""Origin-qualified input references preserve original CAS bytes and actor isolation."""
from uuid import uuid4

from video_service.content_store import ContentStore
from video_service.cpu_agents import reference_path


def test_shared_input_origin_resolves_without_creating_an_actor_blob(tmp_path):
    store = ContentStore(tmp_path)
    uploader, actor = uuid4().hex, uuid4().hex
    original = store.put(uploader, [b'synthetic origin reference'], 'video')
    shared = {**original, 'source_owner_id': uploader}
    source_path = store.path(uploader, original)
    assert store.path(actor, shared) == source_path
    assert reference_path(store.owner_root(actor), shared) == source_path
    assert not (store.owner_root(actor)/original['storage_key']).exists()
    assert store.path(uploader, original).read_bytes() == b'synthetic origin reference'


def test_cpu_wire_allows_pinned_origin_only_for_inputs():
    import pytest
    from test_protocol_layout import command, synthetic_result
    from video_service.rabbitmq_transport import envelope, InvalidMessage
    from jsonschema import Draft202012Validator
    from video_service.agent_protocol import schemas

    cmd = command('encode')
    cmd['inputs']['video']['source_owner_id'] = uuid4().hex
    value = envelope(uuid4().hex, cmd)
    import json
    Draft202012Validator(schemas()['agent.command.v1.schema.json']).validate(json.loads(value.body))
    result = synthetic_result(cmd)
    result['outputs']['video']['source_owner_id'] = uuid4().hex
    with pytest.raises(InvalidMessage):
        envelope(uuid4().hex, cmd, result)


def test_engine_wire_allows_origin_on_input_but_not_output():
    import pytest
    from video_service.engine_protocol import make_command, envelope
    from video_service.cpu_agents import digest
    from video_service.rabbitmq_transport import InvalidMessage
    runtime={'role':'transcribe','family':'model','engine':'whisper-tiny-en','model_sha256':'c'*64,'source_language':'en','target_language':None}
    ref=lambda kind: {'storage_key':'blobs/'+'a'*64,'sha256':'a'*64,'bytes':10,'type':kind}
    cmd=make_command('transcribe',run_id=uuid4().hex,attempt_id=uuid4().hex,generation=1,
                     inputs={'audio':{**ref('audio'),'source_owner_id':uuid4().hex},'timeline':ref('timeline_map')},options={},runtime=runtime)
    envelope(uuid4().hex,cmd)
    result={**{k:cmd[k] for k in ['protocol_version','run_id','attempt_id','generation','agent']},
            'request_sha256':digest(cmd),'status':'completed','transport':'s3_engine',
            'outputs':{'transcript':{**ref('transcript'),'source_owner_id':uuid4().hex}}}
    with pytest.raises(InvalidMessage):envelope(uuid4().hex,cmd,result)
