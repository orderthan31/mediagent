"""Ticket-bound accepted output storage; all roots and bytes are synthetic."""
import os
from uuid import uuid4

from video_service.content_store import ContentStore


def test_ticket_bindings_are_real_paths_with_shared_cas_bytes(tmp_path):
    store = ContentStore(tmp_path)
    owner, first, second, run = [uuid4().hex for _ in range(4)]
    raw = b'{"synthetic":"accepted output"}'
    content = store.put(owner, [raw], 'metadata')
    keys = [f'tickets/{ticket}/nodes/{"a" * 64}/attempts/{run}/outputs/metadata/{content["sha256"]}' for ticket in (first, second)]
    one, two = [store.bind_ticket(owner, key, content) for key in keys]
    assert one['storage_key'] != two['storage_key']
    assert store.path(owner, one).read_bytes() == store.path(owner, two).read_bytes() == raw
    assert os.path.samefile(store.path(owner, content), store.path(owner, one))
    assert os.path.samefile(store.path(owner, one), store.path(owner, two))
    assert store.bind_ticket(owner, keys[0], content) == one


class MemoryS3:
    """Byte-level S3 protocol double, not real object storage acceptance."""
    def __init__(self):
        self.objects = {}

    def put_object(self, **request):
        from botocore.exceptions import ClientError
        key = request['Key']
        assert request['IfNoneMatch'] == '*'
        if key in self.objects:
            raise ClientError({'ResponseMetadata': {'HTTPStatusCode': 412}}, 'PutObject')
        raw = request['Body'].read() if hasattr(request['Body'], 'read') else request['Body']
        assert len(raw) == request['ContentLength']
        self.objects[key] = raw

    def get_object(self, **request):
        import io
        raw = self.objects[request['Key']]
        return {'ContentLength': len(raw), 'Body': io.BytesIO(raw)}


def test_s3_ticket_binding_persists_remote_key_and_reopens_without_cache(tmp_path):
    from video_service.object_store import S3ContentStore
    client = MemoryS3()
    owner, ticket, run = [uuid4().hex for _ in range(3)]
    cache = tmp_path / 'first'
    cache.mkdir()
    store = S3ContentStore(client, 'synthetic-bucket', cache, prefix='ticket-test')
    raw = b'{"synthetic":"remote accepted bytes"}'
    content = store.put(owner, [raw], 'metadata')
    key = f'tickets/{ticket}/nodes/{"a" * 64}/attempts/{run}/outputs/metadata/{content["sha256"]}'
    location = store.bind_ticket(owner, key, content)
    assert client.objects['ticket-test/' + owner + '/' + key] == raw
    other = tmp_path / 'second'
    other.mkdir()
    reopened = S3ContentStore(client, 'synthetic-bucket', other, prefix='ticket-test')
    assert reopened.path(owner, location).read_bytes() == raw
    assert reopened.bind_ticket(owner, key, content) == location


def test_ticket_port_names_and_invalid_bindings(tmp_path):
    import pytest
    store = ContentStore(tmp_path)
    owner, ticket, run = [uuid4().hex for _ in range(3)]
    content = store.put(owner, [b'synthetic guarded content'], 'metadata')
    key = f'tickets/{ticket}/nodes/{"a" * 64}/attempts/{run}/outputs/case_1/{content["sha256"]}'
    reference = store.bind_ticket(owner, key, content)
    assert store.path(owner, reference).read_bytes() == b'synthetic guarded content'
    for bad in [None, [], {}, {**content, 'sha256': '0' * 64}]:
        with pytest.raises(ValueError):
            store.bind_ticket(owner, key, bad)
    with pytest.raises(ValueError):
        store.bind_ticket(owner, '../escape/' + content['sha256'], content)


def test_symlink_or_corrupt_ticket_path_is_rejected_without_overwriting_cas(tmp_path):
    import pytest
    store = ContentStore(tmp_path)
    owner, ticket, run = [uuid4().hex for _ in range(3)]
    content = store.put(owner, [b'synthetic safe content'], 'metadata')
    key = f'tickets/{ticket}/nodes/{"a" * 64}/attempts/{run}/outputs/metadata/{content["sha256"]}'
    outside = tmp_path / 'outside'
    outside.mkdir()
    ticket_root = store.owner_root(owner) / 'tickets'
    ticket_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        store.bind_ticket(owner, key, content)
    ticket_root.unlink()
    reference = store.bind_ticket(owner, key, content)
    path = store.path(owner, reference)
    path.unlink()
    path.write_bytes(b'corrupted alias bytes')
    with pytest.raises(ValueError):
        store.path(owner, reference)
    with pytest.raises(ValueError):
        store.bind_ticket(owner, key, content)
    assert store.path(owner, content).read_bytes() == b'synthetic safe content'
