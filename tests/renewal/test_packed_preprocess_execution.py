"""New saved-definition -> ticket -> installed CPU command profile boundary."""

from test_execution import admin as _admin_fixture
from test_execution import admit, graph, setup
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from test_execution import runtime as _runtime_fixture

admin = _admin_fixture
db = _db_fixture
movie = _movie_fixture
runtime = _runtime_fixture


def test_saved_explicit_preprocess_profile_freezes_revision_three(
    runtime, admin, movie
):
    definition = graph("extract_audio", "preprocess_audio")
    definition["edges"][1]["source"]["port"] = "audio"
    definition["edges"][1]["target"]["port"] = "audio"
    definition["nodes"][1]["options"] = {
        "processing_profile": "silence_pack_v3",
        "audio_filter": "strong",
        "vad_mode": "off",
    }
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, definition)
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed", done
    prepared = next(
        row for row in done["runs"] if row["node_type"] == "preprocess_audio"
    )
    assert prepared["request"]["agent"] == {"id": "preprocess_audio", "revision": "3"}
    assert prepared["request"]["options"] == definition["nodes"][1]["options"]
    assert set(prepared["result"]["outputs"]) == {"audio", "timeline"}
    assert len({r["id"] for r in done["runs"]}) == 2
    assert (
        runtime.get(owner, job["id"])["snapshot"]["definition"]["nodes"][1]["options"]
        == definition["nodes"][1]["options"]
    )


def test_legacy_saved_filter_does_not_auto_upgrade_to_new_cpu_contract(
    runtime, admin, movie
):
    definition = graph("extract_audio", "preprocess_audio")
    definition["edges"][1]["source"]["port"] = "audio"
    definition["edges"][1]["target"]["port"] = "audio"
    definition["nodes"][1]["options"] = {"audio_filter": "strong", "vad_mode": "off"}
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, definition)
    plan = runtime.plan(owner, job["id"])
    assert any("silence_pack_v3" in reason for reason in plan["reasons"])
    assert runtime.get(owner, job["id"])["runs"] == []
