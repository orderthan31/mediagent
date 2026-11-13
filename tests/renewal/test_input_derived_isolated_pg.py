"""Real disposable-PG product admission/adoption; model tools are offline fakes.

No operating DSN, broker queue, provider, or user media is used. The inherited db
fixture requires an explicit disposable DSN and owns its random schema.
"""
from copy import deepcopy
import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_execution import admin, admit, db, movie
from test_model_role_orchestration import formal
from mideagent_orchestrator.model_roles import ModelRoleCoordinator
from mideagent_agents.transcription.model_graph import TranscriptionAgent
from mideagent_agents.translation.model_graph import TranslationAgent
from mideagent_model_runtime.broker import RoleReceiver
from mideagent_model_tools.endpoints import EndpointFailure
from mideagent_model_tools.client import RoleToolBridge
from video_service.canonical import canonical, digest
from video_service.role_policy import tool_context
from video_service.postgres.registry import Registry


@pytest.mark.parametrize("cap", ["auto", "1", "128"])
def test_fresh_v2_coordinator_real_pg_budget_graph_and_adoption(
    db, admin, movie, tmp_path, cap
):
    runtime, owner, seed = formal(db, admin, movie, tmp_path, prepare=False)
    definition = {
        key: deepcopy(seed["snapshot"]["definition"][key])
        for key in ("catalog_version", "revision", "name", "inputs", "nodes", "edges")
    }
    definition["revision"] = 0
    speech = next(n for n in definition["nodes"] if n["type"] == "transcribe")
    registry = Registry(db)
    selected = speech["model_ref"]
    primary = registry.model(owner, selected["model_id"])["versions"][
        str(selected["revision"])
    ]
    fallback = uuid4().hex
    registry.save_model(
        owner, fallback, revision=0, name="offline selected fallback",
        model=primary["model"], connection_id=primary["connection_id"],
        connection_revision=primary["connection_revision"],
        model_types=primary["model_types"], input_modalities=primary["input_modalities"],
        output_modalities=primary["output_modalities"], capabilities=primary["capabilities"],
    )
    speech["fallback_refs"] = [{"model_id": fallback, "revision": 1}]
    for node in definition["nodes"]:
        if node["type"] in {"transcribe", "translate"}:
            node["options"]["max_model_calls"] = cap
    from video_service.editor_contracts import resolve_editor_contracts
    from video_service.renewal_contracts import validate
    validation = validate(resolve_editor_contracts(definition))
    assert validation["valid"], validation
    saved = runtime.save_definition(owner, uuid4().hex, definition)
    job = runtime.create(
        owner, seed["asset_id"], saved["id"], saved["revision"],
        request_id=uuid4().hex, options={"source_language": "en", "target_language": "ko"},
    )
    snapshot = canonical(job["snapshot"])
    def forbidden_transport():
        pytest.fail("this test never opens an operating broker or provider transport")
    coordinator = ModelRoleCoordinator(runtime, SimpleNamespace(
        model_role_factories={"transcription": forbidden_transport, "translation": forbidden_transport},
        model_role_result_store=runtime.store,
    ))
    enrolled = coordinator.auto_enroll_new_job(owner, job["id"], uuid4().hex)
    assert coordinator.enrolled(runtime, owner, job["id"], role="transcription")
    assert coordinator.enrolled(runtime, owner, job["id"], role="translation")
    assert enrolled["runs"] == [] and canonical(enrolled["snapshot"]) == snapshot
    admit(runtime, owner, job["id"])
    for _ in range(2):
        command = runtime.claim_next(owner, job["id"])
        assert command["agent"]["id"] in {"extract_audio", "preprocess_audio"}
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed"
        runtime.accept(owner, command, result)
    command = runtime.claim_next(owner, job["id"])
    assert command["agent"]["id"] == "transcribe"
    expected = 2 if cap == "auto" else int(cap)
    assert command["transcription"]["max_model_calls"] == expected
    if cap == "auto":
        plan = command["transcription"]["model_call_plan"]
        assert plan["planned_units"] == 1 and plan["candidate_count"] == 2
        assert plan["inputs_sha256"] == digest(command["inputs"])
    original_command = canonical(command)
    roles = coordinator.roles
    envelope = roles.enroll(owner, command)
    assert envelope["task"]["version"] == 2
    assert len(envelope["task"]["models"]) == 2
    assert envelope["task"]["max_calls"] == expected
    assert roles.publish_exact(owner, job["id"], command["attempt_id"], lambda _: True)
    bridge = RoleToolBridge(roles, chunk_concurrency=1)
    speech_calls = []
    class SpeechAdapter:
        def __init__(self, pin):
            self.pin = pin

        def transcribe(self, remote_model, audio, language):
            speech_calls.append(self.pin["model_id"])
            if cap != "1" and self.pin["model_id"] == envelope["task"]["models"][0]["model_id"]:
                raise EndpointFailure("offline known failure", code="unavailable")
            return [{"start": 0.1, "end": 0.4, "text": "Offline role fixture"}]

        def close(self):
            pass

    runtime.transcription_runtime.make_adapter = lambda pin, key: SpeechAdapter(pin)
    def speech_tool(model, audio, language):
        return bridge.invoke({
            "task_id": envelope["task"]["task_id"], "chunk_index": 0,
            "candidate_index": envelope["task"]["models"].index(model),
            "model": model, "source_language": language,
            "audio_base64": base64.b64encode(audio).decode(),
            **tool_context(envelope["task"]),
        })
    agent = TranscriptionAgent(tmp_path / "speech-state", speech_tool)
    receiver = RoleReceiver(agent, runtime.store, runtime.store)
    ack = receiver.deliver(envelope)
    assert receiver.deliver(envelope) == ack
    assert len(speech_calls) == (1 if cap == "1" else 2)
    adopted = roles.receive(ack)
    run = next(r for r in adopted["runs"] if r["id"] == command["attempt_id"])
    assert run["status"] == "completed"
    assert canonical(command) == original_command
    translation = roles.dispatch_next(owner, job["id"])
    assert translation["agent"]["id"] == "translate"
    assert translation["translation"]["max_model_calls"] == (1 if cap == "auto" else int(cap))
    translated_envelope = roles.enroll(owner, translation)
    assert roles.publish_exact(owner, job["id"], translation["attempt_id"], lambda _: True)
    translation_calls = []
    current_batch = []
    class TextAdapter:
        _client = SimpleNamespace(timeout=0)

        def chat(self, remote_model, messages):
            translation_calls.append((current_batch[0].chunk_index, 0))
            return json.dumps(["격리된 모델 도구 시험"] * len(current_batch[0].segments))

        def close(self):
            pass

    runtime.translation_runtime.make_adapter = lambda pin, key: TextAdapter()
    def text_tool(task, batch, candidate):
        current_batch[:] = [batch]
        return bridge.invoke_translation({
            "task_id": task["task_id"], "batch_index": batch.chunk_index,
            "candidate_index": candidate, "model": task["models"][candidate],
            "input_sha256": batch.sha256, **tool_context(task),
        })
    translator = TranslationAgent(tmp_path / "translation-state", text_tool)
    text_receiver = RoleReceiver(translator, runtime.store, runtime.store)
    text_ack = text_receiver.deliver(translated_envelope)
    assert text_receiver.deliver(translated_envelope) == text_ack
    final = roles.receive(text_ack)
    translated_run = next(r for r in final["runs"] if r["id"] == translation["attempt_id"])
    assert translated_run["status"] == "completed"
    assert translation_calls == [(0, 0)]
    assert canonical(final["snapshot"]) == snapshot
