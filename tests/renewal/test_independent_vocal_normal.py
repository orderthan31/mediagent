"""Independent vocal role keeps the existing detect/confirm/removal domain policy."""

import importlib.util
import io
import wave
from hashlib import sha256
from uuid import uuid4


def test_vocal_role_owns_detect_confirm_graph_and_keeps_speech_protected(tmp_path):
    assert importlib.util.find_spec("mideagent_models.vocalization") is not None, (
        "independent vocal role missing"
    )
    from mideagent_models.vocalization import VocalizationAgent

    memory = io.BytesIO()
    with wave.open(memory, "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\0\0" * 48000)
    raw = memory.getvalue()
    path = tmp_path / "source.wav"
    path.write_bytes(raw)
    task = {
        "version": 1,
        "role": "vocalization",
        "task_id": uuid4().hex,
        "audio": {"sha256": sha256(raw).hexdigest(), "bytes": len(raw)},
        "models": [{"model_id": uuid4().hex, "revision": 1}],
        "source_language": "en",
        "purpose": "vocalization_regions_v1",
        "strength": "strong",
        "binding_sha256": "a" * 64,
        "max_calls": 4,
    }
    calls = []

    def tool(frozen, request, candidate):
        assert frozen == task and candidate == 0
        phase = request["context"]["phase"]
        calls.append(phase)
        return {
            "status": "received",
            "reply": [
                {"start": 0.3, "end": 1.5, "kind": "breath", "certain": True},
                {"start": 2.4, "end": 2.8, "kind": "speech", "certain": True},
            ]
            if phase == "detect"
            else {"kind": "breath", "safe_to_remove": True, "speech_overlap": False},
        }

    agent = VocalizationAgent(tmp_path / "vocal", tool, chunk_concurrency=1)
    result = agent.run(task, path)
    assert result["status"] == "completed" and result["role"] == "vocalization"
    assert result["model_calls"] == 2 and calls == ["detect", "confirm"]
    assert result["document"]["protected"] == [{"start": 2.4, "end": 2.8}]
    assert result["document"]["removals"] == [
        {"start": 0.45, "end": 1.35, "kind": "breath"}
    ]
    assert {
        "prepare",
        "select",
        "invoke",
        "validate",
        "advance",
        "finish",
    } <= agent.graph_nodes()
    assert agent.run(task, path) == result and calls == ["detect", "confirm"]


from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie

db, admin, movie = _db, _admin, _movie


def test_independent_vocal_result_feeds_existing_cpu_preprocess(
    db, admin, movie, tmp_path
):
    import json
    import subprocess

    import httpx
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.cli import vocal_packet
    from mideagent_models.vocalization import VocalizationAgent
    from test_vocalization_execution import formal_vocal_attempt
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    original = tmp_path / "short-fixture.mp4"
    original.write_bytes(movie)
    longer = tmp_path / "vocal-3s.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-stream_loop",
            "-1",
            "-i",
            str(original),
            "-t",
            "3",
            "-threads",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(longer),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    runtime, owner, command = formal_vocal_attempt(
        db, admin, longer.read_bytes(), tmp_path, max_calls=4
    )
    roles = ModelRoles(runtime)
    envelope = roles.enroll(owner, command)
    assert envelope["role"] == "vocalization"
    roles.publish_exact(owner, command["run_id"], command["attempt_id"], lambda _: True)
    phases = []

    def response(request):
        data = json.loads(request.content)
        detect = data["generationConfig"]["responseSchema"]["type"] == "ARRAY"
        phases.append("detect" if detect else "confirm")
        reply = (
            [
                {"start": 0.3, "end": 1.5, "kind": "breath", "certain": True},
                {"start": 1.7, "end": 1.9, "kind": "speech", "certain": True},
            ]
            if detect
            else {"kind": "breath", "safe_to_remove": True, "speech_overlap": False}
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(reply)}]},
                    }
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(
        response
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=1)
    agent = VocalizationAgent(
        tmp_path / "vocal",
        lambda task, request, candidate: bridge.invoke_vocalization(
            vocal_packet(task, request, candidate)
        ),
    )
    ack = RoleReceiver(
        agent, runtime.store, runtime.store, tool_mode="controlled-audio"
    ).deliver(envelope)
    accepted = roles.receive(ack)
    row = next(r for r in accepted["runs"] if r["id"] == command["attempt_id"])
    assert row["status"] == "completed" and phases == ["detect", "confirm"], {
        "ack": ack["status"],
        "phases": phases,
        "task": agent.state.task(envelope["task"]["task_id"]),
        "chunk": agent.state.chunk(envelope["task"]["task_id"], 0),
    }
    regions = json.loads(runtime.store.read(owner, row["result"]["outputs"]["regions"]))
    assert regions["removals"] == [{"start": 0.45, "end": 1.35, "kind": "breath"}]
    downstream = runtime.claim_next(owner, command["run_id"])
    assert downstream["agent"]["id"] == "preprocess_audio"
    assert downstream["inputs"]["regions"] == row["result"]["outputs"]["regions"]
    result = runtime.execute_command(owner, downstream)
    assert result["status"] == "completed"
    with db.connection() as c:
        assert (
            c.execute(
                "SELECT count(*)n FROM agent_deliveries WHERE node_run_id=%s",
                (command["attempt_id"],),
            ).fetchone()["n"]
            == 0
        )


def test_vocal_only_fresh_draft_enrollment_is_explicit(db, admin, movie, tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from test_vocalization_execution import formal_vocal_attempt
    from video_service.model_role_coordinator import ModelRoleCoordinator

    runtime, owner, ticket = formal_vocal_attempt(
        db, admin, movie, tmp_path, claim=False
    )
    fresh = runtime.create(
        owner,
        ticket["asset_id"],
        ticket["workflow_id"],
        ticket["workflow_revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    coordinator = ModelRoleCoordinator(
        runtime, SimpleNamespace(model_role_factories={"vocalization": lambda: None})
    )
    coordinator.enroll_job(
        owner, fresh["id"], fresh["revision"], uuid4().hex, roles=["vocalization"]
    )
    assert coordinator.inspect(owner, fresh["id"])["available_roles"] == [
        "vocalization"
    ]
    assert coordinator.enrolled(runtime, owner, fresh["id"], role="vocalization")


def test_short_verified_vocal_can_precede_v5_without_enabling_long_vocal_inputs():
    import pytest
    from video_service.long_audio_budget import (
        bounded_vocalization_policy,
        definition_policy,
        policy,
    )

    definition = {
        "nodes": [
            {"type": "extract_audio", "options": {"media_budget": "audio_long_v5"}},
            {
                "type": "vocalize",
                "options": {
                    "batch_policy": "bounded_vocalization_v1",
                    "strength": "strong",
                    "max_model_calls": "4",
                },
            },
        ]
    }
    assert definition_policy(definition) == policy()
    source = {
        "metadata": {"registration_state": "verified", "media": {"duration": 3.0}}
    }
    assert bounded_vocalization_policy(source, definition)["max_source_seconds"] == 300
    with pytest.raises(ValueError):
        bounded_vocalization_policy(
            {
                "metadata": {
                    "registration_state": "verified",
                    "media": {"duration": 301},
                }
            },
            definition,
        )
