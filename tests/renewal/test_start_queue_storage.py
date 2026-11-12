"""Queue policy adapter unit contracts; synthetic local root/MemoryS3, no network/DB."""
import hashlib
import io
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/shared'))
OWNER = 'a' * 32


def test_existing_sdk_has_conditional_put_contract():
    import botocore.session
    shape = botocore.session.get_session().get_service_model('s3').operation_model('PutObject').input_shape
    assert {'IfMatch', 'IfNoneMatch', 'ChecksumSHA256'} <= set(shape.members)


def test_local_policy_revision_cas_and_owner_isolation(tmp_path):
    from video_service.content_store import ContentStore
    from video_service.start_queue_policy import initial_policy, encode_policy, QueueConflict
    store = ContentStore(tmp_path)
    assert store.read_start_queue(OWNER) == (None, None)
    raw = encode_policy({**initial_policy(OWNER), 'revision': 1, 'paused': True})
    token = store.write_start_queue(OWNER, raw, None)
    assert store.read_start_queue(OWNER) == (raw, token)
    assert ContentStore(tmp_path).read_start_queue(OWNER) == (raw, token)
    with pytest.raises(QueueConflict):
        store.write_start_queue(OWNER, raw, None)
    new = encode_policy({**initial_policy(OWNER), 'revision': 2})
    next_token = store.write_start_queue(OWNER, new, token)
    assert next_token != token and store.read_start_queue(OWNER) == (new, next_token)
    with pytest.raises(QueueConflict):
        store.write_start_queue(OWNER, raw, token)
    assert store.read_start_queue('b' * 32) == (None, None)


class ConditionalS3:
    """Only explicit conditional object protocol, no actual S3 acceptance."""
    def __init__(self):
        self.objects, self.calls = {}, []
        self.deny = False
        self.unknown = False

    @staticmethod
    def error(code, status):
        from botocore.exceptions import ClientError
        return ClientError({'Error': {'Code': code, 'Message': 'PRIVATE remote values'},
                            'ResponseMetadata': {'HTTPStatusCode': status}}, 'Synthetic')

    def put_object(self, **request):
        self.calls.append(('PUT', request['Key']))
        if self.deny:
            raise self.error('AccessDenied', 403)
        previous = self.objects.get(request['Key'])
        if request.get('IfNoneMatch') == '*' and previous is not None:
            raise self.error('PreconditionFailed', 412)
        if 'IfMatch' in request and (previous is None or request['IfMatch'] != previous['etag']):
            raise self.error('PreconditionFailed', 412)
        raw = request['Body'].read() if hasattr(request['Body'], 'read') else request['Body']
        assert request['ContentLength'] == len(raw)
        token = '"' + hashlib.md5(raw).hexdigest() + '"'  # Opaque ETag, not content SHA.
        self.objects[request['Key']] = dict(raw=raw, etag=token, metadata=request['Metadata'])
        if self.unknown:
            from botocore.exceptions import ConnectionClosedError
            raise ConnectionClosedError(endpoint_url='https://synthetic.invalid')
        return {'ETag': token}

    def get_object(self, **request):
        self.calls.append(('GET', request['Key']))
        if self.deny:
            raise self.error('AccessDenied', 403)
        value = self.objects.get(request['Key'])
        if value is None:
            raise self.error('NoSuchKey', 404)
        return dict(Body=io.BytesIO(value['raw']), ContentLength=len(value['raw']),
                    Metadata=value['metadata'], ETag=value['etag'])

    def list_objects_v2(self, **request):
        assert request['Prefix'] == 'configured/start-queues/'
        assert request['MaxKeys'] == 20
        if self.deny:
            raise self.error('AccessDenied', 403)
        keys = sorted(key for key in self.objects if key.startswith(request['Prefix']) and key > request.get('StartAfter', ''))
        return {'Contents': [{'Key': key} for key in keys[:20]], 'IsTruncated': len(keys) > 20}


def test_s3_cas_authority_and_unknown_never_reset_or_retry(tmp_path):
    from video_service.object_store import S3ContentStore, ObjectStoreError
    from video_service.start_queue_policy import initial_policy, encode_policy, QueueConflict
    client = ConditionalS3()
    store = S3ContentStore(client, 'synthetic-bucket', tmp_path, prefix='configured')
    assert store.read_start_queue(OWNER) == (None, None)
    raw = encode_policy({**initial_policy(OWNER), 'revision': 1, 'paused': True})
    token = store.write_start_queue(OWNER, raw, None)
    key = 'configured/start-queues/' + OWNER + '.json'
    assert set(client.objects) == {key}
    other = tmp_path / 'other-cache'
    other.mkdir()
    reopened = S3ContentStore(client, 'synthetic-bucket', other, prefix='configured')
    assert reopened.read_start_queue(OWNER) == (raw, token)
    with pytest.raises(QueueConflict):
        reopened.write_start_queue(OWNER, raw, None)
    updated = encode_policy({**initial_policy(OWNER), 'revision': 2, 'paused': False})
    client.unknown = True
    before = len(client.calls)
    with pytest.raises(ObjectStoreError):
        store.write_start_queue(OWNER, updated, token)
    assert [verb for verb, _ in client.calls[before:]] == ['PUT']
    client.unknown = False
    assert reopened.read_start_queue(OWNER)[0] == updated
    client.deny = True
    with pytest.raises(ObjectStoreError) as denied:
        reopened.read_start_queue(OWNER)
    assert denied.value.status == 403 and denied.value.code == 'AccessDenied'
    assert 'PRIVATE' not in str(denied.value)


def test_policy_schema_bounded_and_storage_digest_checked(tmp_path):
    from video_service.object_store import S3ContentStore, ObjectStoreError
    from video_service.start_queue_policy import initial_policy, encode_policy
    for change in [{'revision': True}, {'paused': 0}, {'owner_id': '../escape'}, {'order': ['x']},
                   {'members': [{'job_id': 'b' * 32, 'claim_id': 'c' * 32, 'generation': 1}] * 1001}]:
        with pytest.raises(ValueError):
            encode_policy({**initial_policy(OWNER), **change})
    client = ConditionalS3()
    store = S3ContentStore(client, 'synthetic-bucket', tmp_path, prefix='configured')
    store.write_start_queue(OWNER, encode_policy(initial_policy(OWNER)), None)
    client.objects['configured/start-queues/' + OWNER + '.json']['metadata']['sha256'] = '0' * 64
    with pytest.raises(ObjectStoreError):
        store.read_start_queue(OWNER)


def test_wakeup_discovers_only_bounded_dedicated_queue_namespace(tmp_path):
    from video_service.object_store import S3ContentStore, ObjectStoreError
    from video_service.start_queue_policy import initial_policy, encode_policy
    client = ConditionalS3()
    store = S3ContentStore(client, 'synthetic-bucket', tmp_path, prefix='configured')
    for i in range(21):
        owner = f'{i:032x}'
        store.write_start_queue(owner, encode_policy(initial_policy(owner)), None)
    first, more = store.list_start_queue_owners()
    assert len(first) == 20 and more
    assert store.list_start_queue_owners(first[-1]) == ([f'{20:032x}'], False)
    client.deny = True
    with pytest.raises(ObjectStoreError):
        store.list_start_queue_owners()
