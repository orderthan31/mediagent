"""Formal PG engine-command pin test. Claim only: do NOT execute any GPU."""

from test_execution import admin as _admin_fixture
from test_execution import admit, graph, setup
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from video_service.content_store import ContentStore
from video_service.cpu_agents import digest
from video_service.postgres.engine_runtimes import EngineRuntimes
from video_service.postgres.execution import Execution

admin = _admin_fixture
db = _db_fixture
movie = _movie_fixture


def test_saved_nvidia_profile_claims_only_pinned_engine_command(
    db, admin, movie, tmp_path
):
    runtime = Execution(db, ContentStore(tmp_path), engine_runtime_enabled=True)
    descriptor = {
        "role": "preprocess_audio",
        "family": "gpu",
        "engine": "nvidia-marblenet",
        "model_sha256": "b" * 64,
        "source_language": None,
        "target_language": None,
    }
    EngineRuntimes(db).register(descriptor, revision=0, enabled=True)
    definition = graph("extract_audio", "preprocess_audio")
    definition["edges"][1]["source"]["port"] = "audio"
    definition["edges"][1]["target"]["port"] = "audio"
    definition["nodes"][1]["options"] = {
        "processing_profile": "nvidia_regions_v4",
        "audio_filter": "strong",
        "vad_mode": "nvidia",
    }
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie, definition)
    admit(runtime, owner, job["id"])
    cpu = runtime.claim_next(owner, job["id"])
    assert cpu["agent"]["id"] == "extract_audio"
    runtime.accept(owner, cpu, runtime.execute_command(owner, cpu))
    command = runtime.claim_next(owner, job["id"])
    assert command["protocol_version"] == 2
    assert command["agent"]["family"] == "gpu"
    assert command["runtime"] == descriptor
    assert command["options"] == definition["nodes"][1]["options"]
    assert command["agent"]["revision"] == digest(descriptor)
    # This fixture deliberately ends BEFORE engine dispatch / GPU startup.
    assert runtime.get(owner, job["id"])["runs"][-1]["result"] is None
