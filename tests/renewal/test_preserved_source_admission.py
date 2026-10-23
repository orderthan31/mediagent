"""Preserved large sources must not be silently admitted to bounded processors."""

import contextlib

import pytest
from video_service.content_store import MAX_CONTENT
from video_service.postgres.execution import Execution


class ReadOnlyPrerequisite:
    @contextlib.contextmanager
    def connection(self):
        yield self

    def execute(self, query, params):
        assert query.startswith("SELECT * FROM jobs")
        return self

    def fetchone(self):
        return None


def test_unsupported_large_source_workflow_refused_before_materialization_or_ticket_insert():
    runtime = Execution.__new__(Execution)
    runtime.database = ReadOnlyPrerequisite()
    runtime._shared_asset = lambda *_: {
        "bytes": MAX_CONTENT + 1,
        "owner_id": "a" * 32,
        "sha256": "b" * 64,
        "storage_key": "sha256:" + "b" * 64,
        "metadata": {"registration_state": "verified"},
    }

    class Store:
        def path(self, *_):
            raise AssertionError("must reject before downloading a large original")

    runtime.store = Store()
    runtime._job_definition = lambda *_: ('a' * 32, {'nodes': [{'id': 'audio', 'type': 'extract_audio'}]})
    with pytest.raises(ValueError, match="256 MiB"):
        runtime.create("a" * 32, "c" * 32, "d" * 32, 1, request_id="bounded-processing")
