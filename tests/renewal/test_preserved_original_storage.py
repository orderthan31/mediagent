"""Narrow storage/provenance regressions; no operating originals or providers."""

import hashlib
import io
from datetime import UTC, datetime

import pytest
from video_service.content_store import MAX_CONTENT, ContentStore
from video_service.object_store import S3ContentStore, validate_reference
from video_service.postgres.intake import Intake, public_asset

OWNER = "a" * 32


def test_stored_original_reference_can_exceed_processing_limit():
    validate_reference(
        {
            "storage_key": "blobs/" + "b" * 64,
            "sha256": "b" * 64,
            "bytes": MAX_CONTENT + 1,
            "type": "video",
        }
    )


def test_normal_upload_limit_is_not_relaxed():
    with pytest.raises(ValueError, match="256 MiB"):
        Intake(None, None).upload_create(
            OWNER, "large.mp4", MAX_CONTENT + 1, "bounded-upload"
        )


class Peer:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kw):
        from botocore.exceptions import ClientError

        if kw["Key"] in self.objects:
            raise ClientError(
                {"ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject"
            )
        self.objects[kw["Key"]] = kw["Body"].read()

    def get_object(self, **kw):
        raw = self.objects[kw["Key"]]
        return {"Body": io.BytesIO(raw), "ContentLength": len(raw)}


def test_explicit_file_import_verifies_actual_remote_bytes(tmp_path):
    source = tmp_path / "preserved.mp4"
    raw = b"preserved original\x00" * 2048
    source.write_bytes(raw)
    cache = tmp_path / "cache"
    cache.mkdir()
    peer = Peer()
    store = S3ContentStore(peer, "preserved-assets", cache, prefix="originals")
    sha = hashlib.sha256(raw).hexdigest()
    ref = store.import_original_file(OWNER, source, sha256=sha, byte_count=len(raw))
    assert ref["sha256"] == sha and ref["bytes"] == len(raw)
    assert source.read_bytes() == raw
    assert (
        store.import_original_file(OWNER, source, sha256=sha, byte_count=len(raw))
        == ref
    )
    assert len(peer.objects) == 1
    peer.objects[next(iter(peer.objects))] = b"x" * len(raw)
    with pytest.raises(ValueError):
        store.import_original_file(OWNER, source, sha256=sha, byte_count=len(raw))


def test_large_local_reference_is_stream_verified_without_relaxing_put(tmp_path):
    size = MAX_CONTENT + 1
    sha = hashlib.sha256()
    remaining = size
    while remaining:
        block = b"\0" * min(1024 * 1024, remaining)
        sha.update(block)
        remaining -= len(block)
    store = ContentStore(tmp_path)
    root = store.owner_root(OWNER) / "blobs"
    root.mkdir()
    path = root / sha.hexdigest()
    with path.open("wb") as stream:
        stream.seek(size - 1)
        stream.write(b"\0")
    reference = {
        "storage_key": "blobs/" + sha.hexdigest(),
        "sha256": sha.hexdigest(),
        "bytes": size,
        "type": "video",
    }
    assert store.path(OWNER, reference) == path


def test_legacy_unknown_uploader_does_not_become_storage_custodian():
    value = public_asset(
        {
            "id": "b" * 32,
            "owner_id": OWNER,
            "filename": "preserved.mp4",
            "bytes": 9,
            "sha256": "c" * 64,
            "created_at": datetime.now(UTC),
            "metadata": {
                "registration_state": "verified",
                "legacy_origin": {
                    "namespace": "legacy/windows-original",
                    "original_owner_id": None,
                    "imported_by": OWNER,
                },
            },
        }
    )
    assert value["uploaded_by"] is None
    assert value["provenance"]["kind"] == "preserved_legacy"
    assert value["provenance"]["imported_by"] == OWNER
