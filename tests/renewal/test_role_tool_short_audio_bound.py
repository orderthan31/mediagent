"""Normal short input must not allocate the whole 1GiB admission ceiling."""

from test_execution import db as _db, admin as _admin, movie as _movie
from test_role_bridge_boundaries import bridge_case
from video_service.model_role_tool import RoleToolBridge

db, admin, movie = _db, _admin, _movie


def test_bridge_reads_only_frozen_actual_audio_bytes(
    db, admin, movie, tmp_path, monkeypatch
):
    runtime, roles, owner, command, _, packet = bridge_case(db, admin, movie, tmp_path)
    original = runtime.store.read
    reads = []

    def bounded(who, ref, *, limit=1024 * 1024):
        if ref == command["inputs"]["audio"]:
            reads.append(limit)
            assert limit == ref["bytes"], (
                "whole policy ceiling must not be allocated for short audio"
            )
        return original(who, ref, limit=limit)

    monkeypatch.setattr(runtime.store, "read", bounded)

    class Adapter:
        def transcribe(self, *_):
            return []

        def close(self):
            pass

    monkeypatch.setattr(
        runtime.transcription_runtime, "make_adapter", lambda *_: Adapter()
    )
    assert RoleToolBridge(roles, chunk_concurrency=1).invoke(packet) == []
    assert reads == [command["inputs"]["audio"]["bytes"]]
