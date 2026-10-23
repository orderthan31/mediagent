"""Common node insertion keeps engine-v2 distinct from CPU-v1 agent revision2.

Only disposable PG and command construction; never model/GPU/provider execution.
"""

from uuid import uuid4

import pytest
from test_engine_execution import speech_graph
from test_execution import admit
from test_execution import movie as movie  # noqa: PLC0414 - explicit pytest fixture export
from test_foundation import admin as admin  # noqa: PLC0414 - explicit pytest fixture export
from test_foundation import db as db  # noqa: PLC0414 - explicit pytest fixture export
from video_service.content_store import ContentStore
from video_service.cpu_input_policy import lease_seconds
from video_service.engine_protocol import validate_command
from video_service.postgres.engine_runtimes import EngineRuntimes
from video_service.postgres.execution import Execution


def test_valid_engine_common_insert_retains_120_second_lease(
    db, admin, movie, tmp_path
):
    store = ContentStore(tmp_path)
    runtime = Execution(db, store, engine_runtime_enabled=True)
    registry = EngineRuntimes(db)
    for role, engine in [
        ("transcribe", "whisper-tiny-en"),
        ("translate", "opus-en-de-int8"),
    ]:
        registry.register(
            {
                "role": role,
                "family": "model",
                "engine": engine,
                "model_sha256": "a" * 64,
                "source_language": "en",
                "target_language": "de" if role == "translate" else None,
            },
            revision=0,
            enabled=True,
        )
    source = runtime.ingest(admin[0]["id"], "small-lease-fixture.mp4", movie)
    definition = uuid4().hex
    saved = runtime.save_definition(admin[0]["id"], definition, speech_graph())
    job = runtime.create(
        admin[0]["id"],
        source["asset_id"],
        definition,
        saved["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "de"},
    )
    admit(runtime, admin[0]["id"], job["id"])
    # Real CAS refs, only command-contract types; no audio inference/decode is invoked.
    refs = {
        port: store.put(admin[0]["id"], [b"explicit-command-fixture"], kind)
        for port, kind in [("audio", "audio"), ("timeline", "timeline_map")]
    }
    with db.connection() as connection:
        frozen = runtime._job(connection, admin[0]["id"], job["id"], lock=True)
        node = next(
            n
            for n in frozen["snapshot"]["definition"]["nodes"]
            if n["type"] == "transcribe"
        )
        row, command = runtime._insert_run(connection, frozen, node, refs, "running")
        assert validate_command(command) == command
        assert command["protocol_version"] == 2 and set(command["agent"]) == {
            "id",
            "family",
            "revision",
        }
        assert row["agent_revision"] == command["agent"]["revision"]
        remaining = connection.execute(
            "SELECT extract(epoch from lease_expires_at-now()) AS seconds FROM node_runs WHERE id=%s",
            (row["id"],),
        ).fetchone()["seconds"]
        assert 119 <= remaining <= 120
    with db.connection() as connection:
        persisted = connection.execute(
            "SELECT request FROM node_runs WHERE id=%s", (row["id"],)
        ).fetchone()
        assert persisted["request"] == command
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM artifacts WHERE job_id=%s", (job["id"],)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize("role", ["encode", "validate_video"])
@pytest.mark.parametrize(("revision", "seconds"), [("1", 120), ("2", 9600)])
def test_cpu_v1_wire_agent_revision_leases_unchanged(role, revision, seconds):
    assert (
        lease_seconds(
            {"protocol_version": 1, "agent": {"id": role, "revision": revision}}
        )
        == seconds
    )
