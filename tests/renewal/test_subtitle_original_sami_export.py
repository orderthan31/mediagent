import json
from types import SimpleNamespace

import pytest
from video_service.content_store import ContentStore
from video_service.postgres.subtitle_tracks import SubtitleTracks
from video_service.subtitle_tracks import MANIFEST_BYTES, POLICY, TRACK_BYTES


@pytest.mark.parametrize("original_language,rendered", [("en", "en"), ("auto", "und")])
def test_original_and_translation_each_export_srt_and_sami(
    tmp_path, original_language, rendered
):
    service = SubtitleTracks(
        SimpleNamespace(store=ContentStore(tmp_path), database=None)
    )
    owner = "a" * 32
    rows = [{"id": "literal-id", "start": 0.0, "end": 1.0, "text": "Reviewed original"}]
    ref = service.put(owner, rows, "transcript", TRACK_BYTES)
    lineage = service.put(
        owner,
        {
            "rows": [
                {
                    "literal_parent_id": "literal-id",
                    "children": [{"id": "literal-id", "start": 0.0, "end": 1.0}],
                }
            ]
        },
        "metadata",
        TRACK_BYTES,
    )
    doc = {
        "version": 1,
        "policy": POLICY,
        "source_video_sha256": "b" * 64,
        "duration_seconds": 2.0,
        "review": {"id": "c" * 32, "revision": 1},
        "tracks": {
            "original": {
                "language": original_language,
                "transcript": ref,
                "lineage": lineage,
            },
            "translated": {"language": "ko", "transcript": ref, "lineage": lineage},
        },
    }
    bundle = service.put(owner, doc, "subtitle_tracks", MANIFEST_BYTES)
    outputs = service.export(
        {
            "owner_id": owner,
            "snapshot": {"asset": {"sha256": "b" * 64, "media": {"duration": 2.0}}},
        },
        {"options": {"format": "srt_smi"}},
        bundle,
    )
    manifest = json.loads(service.store.read(owner, outputs["manifest"]))
    original = manifest["tracks"]["original"]
    assert set(original["files"]) == {"srt", "smi"}
    assert original["transcript"] == ref and original["lineage"] == lineage
    assert (
        "lang: " + rendered + ";"
        in service.store.read(owner, original["files"]["smi"]["reference"]).decode()
    )
    assert original["language"] == original_language


def test_plan_never_stages_subtitle_cas_before_admission(monkeypatch):
    from contextlib import nullcontext

    from video_service.postgres.execution import Execution

    runtime = object.__new__(Execution)
    runtime.store = None
    runtime.database = SimpleNamespace(connection=lambda: nullcontext(None))
    runtime._preflight_cpu_inputs = lambda *_: None
    runtime._job = lambda *_args, **_kwargs: {"id": "job"}
    runtime._plan = lambda *_args: {"ready": False}

    def forbidden(*_args):
        raise AssertionError("plan must not materialize/serialize subtitle outputs")

    monkeypatch.setattr(SubtitleTracks, "preflight", forbidden)
    assert runtime.plan("owner", "job") == {"ready": False}
