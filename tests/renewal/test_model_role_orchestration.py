"""Narrow actual product scheduler/PG to role and back; no live provider."""

import json
import os
from uuid import uuid4

import httpx
import pytest
from test_execution import admin as _admin_fixture
from test_execution import admit
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.cpu_agents import canonical
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

db, admin, movie = _db_fixture, _admin_fixture, _movie_fixture


def formal(db, admin, movie, tmp_path, store=None):
    credentials = CredentialStore(db, os.urandom(32))
    owner = admin[0]["id"]
    refs = []
    registry = Registry(db)
    for speech in [True, False]:
        cid, mid = uuid4().hex, uuid4().hex
        registry.save_connection(
            owner,
            cid,
            revision=0,
            name="isolated role mapping",
            provider="openai_compatible",
            protocol="gemini",
            endpoint="http://127.0.0.1:9419/v1",
        )
        credentials.save(owner, cid, revision=1, secret=uuid4().hex)
        registry.save_model(
            owner,
            mid,
            revision=0,
            name="controlled mapping",
            model="gemini-fixture",
            connection_id=cid,
            connection_revision=2,
            model_types=["speech_recognition" if speech else "text"],
            input_modalities=["audio" if speech else "text"],
            output_modalities=["text"],
            capabilities=["speech_recognition" if speech else "text_generation"],
        )
        refs.append({"model_id": mid, "revision": 1})
    kwargs = dict(
        transport_factory=lambda: httpx.MockTransport(
            lambda _: pytest.fail("central model path forbidden")
        ),
        approved_origins={"http://127.0.0.1:9419"},
        mode="controlled_http",
    )
    (tmp_path / "objects").mkdir()
    runtime = Execution(
        db,
        store or ContentStore(tmp_path / "objects"),
        transcription_runtime=TranscriptionRuntime(credentials, **kwargs),
        translation_runtime=TranslationRuntime(credentials, **kwargs),
    )
    graph = audio_graph(*refs)
    for node in graph["nodes"]:
        node["options"]["media_budget"] = "audio_long_v5"
        if node["type"] == "preprocess_audio":
            node["options"]["processing_profile"] = "regions_long_v5"
        if node["type"] == "transcribe":
            node["options"].update(
                clock_policy="packed_projection_v5",
                batch_policy="bounded_60s_v1",
                max_model_calls="3",
            )
        if node["type"] == "translate":
            node["options"].update(
                batch_policy="bounded_100x16k_v1", max_model_calls="3"
            )
    saved = runtime.save_definition(owner, uuid4().hex, graph)
    asset = runtime.ingest(owner, "synthetic-role.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        saved["id"],
        saved["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    admit(runtime, owner, job["id"])
    for _ in range(2):
        command = runtime.claim_next(owner, job["id"])
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed"
        runtime.accept(owner, command, result)
    command = runtime.claim_next(owner, job["id"])
    assert command["agent"]["id"] == "transcribe"
    return runtime, owner, command


def test_product_attempt_mapping_independent_graph_adoption_next_node(
    db, admin, movie, tmp_path
):
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, command = formal(db, admin, movie, tmp_path)
    roles = ModelRoles(runtime)
    envelope = roles.enroll(owner, command)
    assert envelope["task"]["task_id"] == command["attempt_id"]
    assert envelope["task"]["model"] == {
        k: command["transcription"]["candidates"][0][k]
        for k in ["model_id", "revision"]
    }
    assert envelope["task"]["max_calls"] == 3
    assert not any(
        x in canonical(envelope)
        for x in [b"credential_ref", b"endpoint", b"owner_id", b"candidates"]
    )
    from video_service.postgres import Conflict

    with pytest.raises(Conflict, match="independent_role_owns_attempt"):
        runtime.execute_command(owner, command)
    published = []
    assert roles.publish_exact(
        owner,
        command["run_id"],
        command["attempt_id"],
        lambda packet: published.append(packet) or True,
    )
    assert published == [envelope]
    calls = []
    role = TranscriptionAgent(
        tmp_path / "role",
        lambda model, audio, language: (
            calls.append(model)
            or [{"start": 0.1, "end": 0.4, "text": "Controlled role transcript"}]
        ),
    )
    ack = RoleReceiver(
        role, runtime.store, runtime.store, tool_mode="controlled"
    ).deliver(envelope)

    def forbidden(*_):
        pytest.fail("central execution must not execute role")

    runtime.execute_command = forbidden
    first = roles.receive(ack)
    assert first["status"] == "running"
    asr = next(r for r in first["runs"] if r["id"] == command["attempt_id"])
    assert asr["status"] == "completed"
    assert asr["result"]["transport"] == "independent_model_role"
    downstream = roles.dispatch_next(owner, command["run_id"])
    assert downstream["agent"]["id"] == "translate"
    assert downstream["inputs"]["transcript"] == asr["result"]["outputs"]["transcript"]
    assert len(calls) == 1
    assert roles.receive(ack)["id"] == command["run_id"]
    with db.connection() as c:
        assert c.execute("SELECT count(*) n FROM model_role_tasks").fetchone()["n"] == 1
        assert (
            c.execute(
                "SELECT count(*) n FROM agent_deliveries WHERE node_run_id=%s",
                (command["attempt_id"],),
            ).fetchone()["n"]
            == 0
        )
    assert not roles.publish_exact(
        owner,
        command["run_id"],
        command["attempt_id"],
        lambda _: pytest.fail("accepted role not resent"),
    )


def test_scoped_registry_tool_bridge_validates_chunk_before_frozen_credential_call(
    db, admin, movie, tmp_path
):
    import base64

    from video_service.audio_batches import split_normalized_audio
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, command = formal(db, admin, movie, tmp_path)
    roles = ModelRoles(runtime)
    packet = roles.enroll(owner, command)
    assert roles.publish_exact(
        owner, command["run_id"], command["attempt_id"], lambda _: True
    )
    batch = list(
        split_normalized_audio(runtime.store.read(owner, command["inputs"]["audio"]))
    )[0]
    body = {
        "task_id": packet["task"]["task_id"],
        "chunk_index": 0,
        "model": packet["task"]["model"],
        "source_language": "en",
        "audio_base64": base64.b64encode(batch.audio).decode(),
    }
    calls = []

    def transport(request):
        with db.connection() as c:
            assert (
                c.execute("SELECT status FROM model_role_tool_calls").fetchone()[
                    "status"
                ]
                == "started"
            )
        calls.append(request.headers.get("x-goog-api-key"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"start":0.1,"end":0.4,"text":"Pinned bridge"}]'
                                }
                            ]
                        },
                    }
                ]
            },
        )

    runtime.transcription_runtime.transport_factory = lambda: httpx.MockTransport(
        transport
    )
    frozen = command["transcription"]["candidates"][0]
    key = runtime.transcription_runtime.credentials.resolve(
        owner, frozen["connection_id"], frozen["credential_ref"]
    )
    Registry(db).save_model(
        owner,
        frozen["model_id"],
        revision=1,
        name="later head",
        model="later-unselected",
        connection_id=frozen["connection_id"],
        connection_revision=frozen["connection_revision"],
        model_types=frozen["model_types"],
        input_modalities=frozen["input_modalities"],
        output_modalities=frozen["output_modalities"],
        capabilities=frozen["capabilities"],
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    with pytest.raises(ValueError):
        bridge.invoke({**body, "model": {**body["model"], "revision": 2}})
    with pytest.raises(ValueError):
        bridge.invoke({**body, "chunk_index": 1})
    assert calls == []
    first = bridge.invoke(body)
    assert first == [{"start": 0.1, "end": 0.4, "text": "Pinned bridge"}]
    assert bridge.invoke(body) == first and calls == [key]
    with db.connection() as c:
        assert (
            c.execute("SELECT count(*) n FROM model_role_tool_calls").fetchone()["n"]
            == 1
        )


def test_scoped_tool_client_binds_task_chunk_and_language(tmp_path, monkeypatch):
    import base64

    from mideagent_models.cli import ScopedSpeechTool

    monkeypatch.setenv("TEST_ROLE_TOOL_KEY", "test-only-not-a-provider-key")
    tool = ScopedSpeechTool(
        {
            "tool_url": "http://127.0.0.1:9932/tool",
            "allow_controlled_loopback": True,
            "credential_env": "TEST_ROLE_TOOL_KEY",
            "timeout_seconds": 1,
            "tool_contract": "registry_scoped_v1",
        }
    )
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return b"[]"

    def open(request, timeout):
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(tool.client, "open", open)
    task = {
        "task_id": "a" * 32,
        "model": {"model_id": "b" * 32, "revision": 1},
        "source_language": "en",
    }
    tool.for_chunk(task, {"index": 7})(task["model"], b"RIFF verified data", "en")
    assert requests == [
        {
            "task_id": "a" * 32,
            "chunk_index": 7,
            "model": task["model"],
            "source_language": "en",
            "audio_base64": base64.b64encode(b"RIFF verified data").decode(),
        }
    ]
