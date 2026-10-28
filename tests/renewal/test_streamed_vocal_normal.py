"""Whole-source vocal processing keeps bounded provider clips on original PCM time."""

import hashlib
import wave
from uuid import uuid4

from mideagent_models.vocalization import VocalizationAgent


def test_321_second_vocal_source_is_streamed_without_widening_provider_requests(
    tmp_path,
):
    path = tmp_path / "321s.wav"
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(321):
            f.writeframesraw(b"\0\0" * 16000)
    with path.open("rb") as f:
        sha = hashlib.file_digest(f, "sha256").hexdigest()
    task = {
        "version": 2,
        "role": "vocalization",
        "task_id": uuid4().hex,
        "audio": {"sha256": sha, "bytes": path.stat().st_size},
        "models": [{"model_id": uuid4().hex, "revision": 1}],
        "source_language": "en",
        "purpose": "vocalization_regions_v1",
        "strength": "strong",
        "binding_sha256": "a" * 64,
        "max_calls": 32,
        "batch_policy": "streamed_vocalization_v2",
    }
    calls = []

    def tool(t, request, candidate):
        context = request["context"]
        assert context["source_frames"] == 321 * 16000
        assert context["source_contract"] == "streamed_vocalization_v2"
        assert all(
            0 < clip["end_frame"] - clip["start_frame"] <= 60 * 16000
            for clip in context["clips"]
        )
        calls.append(context["phase"])
        return {
            "status": "received",
            "reply": [
                {"start": 3.0, "end": 4.5, "kind": "breath", "certain": True},
                {"start": 6.4, "end": 6.8, "kind": "speech", "certain": True},
            ]
            if context["phase"] == "detect"
            else {"kind": "breath", "safe_to_remove": True, "speech_overlap": False},
        }

    agent = VocalizationAgent(tmp_path / "role", tool, chunk_concurrency=1)
    result = agent.run(task, path)
    assert result["status"] == "completed" and result["model_calls"] == 22
    assert calls.count("detect") == 11 and calls.count("confirm") == 11
    assert result["document"]["source_frames"] == 321 * 16000
    assert result["document"]["protected"][-1]["end"] > 300
    assert result["document"]["removals"][-1]["start"] > 300
    assert agent.run(task, path) == result and len(calls) == 22


from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie

db, admin, movie = _db, _admin, _movie


def test_long_vocal_policy_separates_provider_requests_and_preserves_old_source_caps():
    from video_service.long_audio_budget import (
        bounded_vocalization_policy,
        definition_policy,
        policy,
    )

    graph = {
        "nodes": [
            {"type": "extract_audio", "options": {"media_budget": "audio_long_v5"}},
            {
                "type": "vocalize",
                "options": {
                    "batch_policy": "streamed_vocalization_v2",
                    "strength": "strong",
                    "max_model_calls": "4096",
                },
            },
        ]
    }
    assert definition_policy(graph) == policy()
    bound = bounded_vocalization_policy(
        {
            "metadata": {
                "registration_state": "verified",
                "media": {"duration": 5453.12},
            }
        },
        graph,
    )
    assert (
        bound["id"] == "streamed_vocalization_v2"
        and bound["max_source_seconds"] == 21600
    )
    assert (
        bound["request_max_seconds"] == 60
        and bound["request_max_audio_bytes"] == 2 * 1024 * 1024
    )


def test_long_vocal_product_adopts_whole_source_regions_into_long_preprocessor(
    db, admin, movie, tmp_path
):
    import json
    import subprocess
    from types import SimpleNamespace
    from uuid import uuid4

    import httpx
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.cli import vocal_packet
    from test_vocalization_execution import formal_vocal_attempt
    from video_service.model_role_coordinator import ModelRoleCoordinator
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, prior = formal_vocal_attempt(
        db, admin, movie, tmp_path, max_calls=4, claim=False
    )
    with db.connection() as c:
        graph = c.execute(
            "SELECT snapshot->'definition' definition FROM jobs WHERE id=%s",
            (prior["id"],),
        ).fetchone()["definition"]
    for n in graph["nodes"]:
        if n["type"] == "vocalize":
            n["options"].update(
                batch_policy="streamed_vocalization_v2", max_model_calls="32"
            )
        else:
            n["options"]["media_budget"] = "audio_long_v5"
        if n["type"] == "preprocess_audio":
            n["options"]["processing_profile"] = "regions_long_v5"
    graph = {
        k: graph[k]
        for k in ["catalog_version", "revision", "name", "inputs", "nodes", "edges"]
    }
    graph["revision"] = 0
    from video_service.renewal_contracts import validate

    assert validate(graph)["valid"], validate(graph)
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    original = tmp_path / "original.mp4"
    original.write_bytes(movie)
    longer = tmp_path / "321s.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:r=1:d=321",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=321",
            "-t",
            "321",
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
        timeout=45,
    )
    import os
    from pathlib import Path

    import boto3
    from botocore.config import Config
    from video_service.object_agent import ObjectAgentExecutor
    from video_service.object_store import S3ContentStore

    keys = json.loads(Path("/fixture/private/operator.json").read_text())
    s3 = boto3.client(
        "s3",
        endpoint_url="https://model-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=keys["object_user"],
        aws_secret_access_key=keys["object_password"],
        verify="/fixture/private/ca.pem",
        config=Config(
            signature_version="s3v4",
            retries={"total_max_attempts": 1},
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )
    cache = tmp_path / "appcache"
    cache.mkdir()
    peer = tmp_path / "peercache"
    peer.mkdir()
    runtime.store = S3ContentStore(s3, "model-role-boundary", cache, prefix="inputs")
    from video_service.postgres.ticket_artifacts import TicketArtifacts

    runtime.ticket_artifacts = TicketArtifacts(runtime.store)
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH"}}
    env.update(
        LONG_VOCAL_S3_ACCESS=keys["object_user"],
        LONG_VOCAL_S3_SECRET=keys["object_password"],
        LONG_VOCAL_OBJECT_CONFIG=json.dumps(
            {
                "endpoint": "https://model-objects:9000",
                "bucket": "model-role-boundary",
                "prefix": "inputs",
                "region": "us-east-1",
                "cache_root": str(peer),
                "access_key_env": "LONG_VOCAL_S3_ACCESS",
                "secret_key_env": "LONG_VOCAL_S3_SECRET",
                "ca_file": "/fixture/private/ca.pem",
            }
        ),
    )
    runtime.agent_executor = ObjectAgentExecutor(
        "LONG_VOCAL_OBJECT_CONFIG", environ=env
    )
    asset = runtime.ingest(owner, "controlled-321s.mp4", longer.read_bytes())
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    coordinator = ModelRoleCoordinator(
        runtime, SimpleNamespace(model_role_factories={"vocalization": lambda: None})
    )
    coordinator.enroll_job(
        owner, job["id"], job["revision"], uuid4().hex, roles=["vocalization"]
    )
    plan = runtime.plan(owner, job["id"])
    assert plan["ready"], plan["reasons"]
    consent = runtime.confirm(owner, job["id"], plan["token"], uuid4().hex)
    runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
    command = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, command)
    assert result["status"] == "completed"
    runtime.accept(owner, command, result)
    command = runtime.claim_next(owner, job["id"])
    assert command is not None, {
        "status": runtime.get(owner, job["id"])["status"],
        "runs": [
            (r["node_id"], r["status"], r.get("result"))
            for r in runtime.get(owner, job["id"])["runs"]
        ],
        "inspect": runtime.plan(owner, job["id"])["reasons"],
    }
    roles = ModelRoles(runtime)
    envelope = roles.enroll(owner, command)
    assert envelope["task"]["version"] == 2
    roles.publish_exact(owner, command["run_id"], command["attempt_id"], lambda _: True)
    phases = []

    def response(request):
        data = json.loads(request.content)
        detect = data["generationConfig"]["responseSchema"]["type"] == "ARRAY"
        phases.append("detect" if detect else "confirm")
        reply = (
            [
                {"start": 3, "end": 4.5, "kind": "breath", "certain": True},
                {"start": 6.4, "end": 6.8, "kind": "speech", "certain": True},
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
        tmp_path / "independent",
        lambda task, request, candidate: bridge.invoke_vocalization(
            vocal_packet(task, request, candidate)
        ),
    )
    ack = RoleReceiver(
        agent, runtime.store, runtime.store, tool_mode="controlled-audio"
    ).deliver(envelope)
    accepted = roles.receive(ack)
    row = next(r for r in accepted["runs"] if r["id"] == command["attempt_id"])
    assert row["status"] == "completed", {
        "ack": ack["status"],
        "phases": phases,
        "task": agent.state.task(envelope["task"]["task_id"]),
    }
    regions = json.loads(runtime.store.read(owner, row["result"]["outputs"]["regions"]))
    assert (
        regions["source_frames"] > 300 * 16000
        and regions["removals"][-1]["start"] > 300
    )
    downstream = runtime.claim_next(owner, job["id"])
    assert downstream["agent"]["revision"] == "5"
    done = runtime.execute_command(owner, downstream)
    assert done["status"] == "completed", done
    runtime.accept(owner, downstream, done)
    assert phases.count("detect") == 11 and phases.count("confirm") == 11


def test_preview_exposes_vocal_call_budget_and_cost_consent_before_job_creation(
    db, admin, movie, tmp_path
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient
    from test_foundation import login
    from test_vocalization_execution import formal_vocal_attempt

    runtime, _owner, job = formal_vocal_attempt(
        db, admin, movie, tmp_path, max_calls=4, claim=False
    )
    runtime.vocalization_runtime.requires_paid = lambda _: True
    app = create_app(
        db,
        allowed_origins=["http://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
        local_execution=True,
        credential_store=runtime.vocalization_runtime.credentials,
        vocalization_runtime=runtime.vocalization_runtime,
    )
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login(client, admin)
    response = client.post(
        "/api/work-entry/preview",
        json={
            "asset_id": job["asset_id"],
            "definition_id": job["workflow_id"],
            "definition_revision": job["workflow_revision"],
            "options": {"source_language": "en", "target_language": "ko"},
        },
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert "vocalization" in plan["paid_roles"]
    vocal = next(r for r in plan["model_call_budgets"] if r["role"] == "vocalize")
    assert vocal["max_calls"] == 4 and vocal["minimum_audio_calls"] == 1
