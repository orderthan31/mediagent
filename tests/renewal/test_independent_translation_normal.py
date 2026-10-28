"""Independent translation preserves the existing bounded text contract."""

import importlib.util
import json
from hashlib import sha256
from uuid import uuid4

from video_service.cpu_agents import canonical


def test_role_local_translation_batches_keep_ids_times_languages_and_completed_output(
    tmp_path,
):
    assert importlib.util.find_spec("mideagent_models.translation") is not None, (
        "translation role not implemented"
    )
    from mideagent_models.translation import TranslationAgent

    rows = [
        {"id": f"cue-{i}", "start": i * 2.0, "end": i * 2.0 + 1.0, "text": f"line {i}"}
        for i in range(205)
    ]
    raw = canonical(rows)
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    task = {
        "version": 1,
        "role": "translation",
        "task_id": uuid4().hex,
        "transcript": {"sha256": sha256(raw).hexdigest(), "bytes": len(raw)},
        "models": [{"model_id": uuid4().hex, "revision": 3}],
        "source_language": "en",
        "target_language": "ko",
        "batch_policy": "bounded_100x16k_v1",
        "max_calls": 4,
    }
    calls = []

    def tool(frozen, batch, candidate):
        assert frozen == task and candidate == 0
        calls.append(batch.chunk_index)
        return {
            "status": "received",
            "reply": json.dumps(["KO " + r["text"] for r in batch.segments]),
        }

    agent = TranslationAgent(tmp_path / "state", tool, chunk_concurrency=1)
    result = agent.run(task, path)
    assert result["status"] == "completed" and result["role"] == "translation"
    assert result["model_calls"] == 3 and result["completed_chunks"] == 3
    assert [r["text"] for r in result["segments"]] == ["KO " + r["text"] for r in rows]
    assert all(
        {k: v for k, v in a.items() if k != "text"}
        == {k: v for k, v in b.items() if k != "text"}
        for a, b in zip(rows, result["segments"])
    )
    assert {
        "prepare",
        "select",
        "invoke",
        "validate",
        "advance",
        "finish",
    } <= agent.graph_nodes()
    assert agent.run(task, path) == result and calls == [0, 1, 2]


from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie

db, admin, movie = _db, _admin, _movie


def test_existing_asr_then_independent_translation_adopts_without_central_execution(
    db, admin, movie, tmp_path
):
    import httpx
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from mideagent_models.translation import TranslationAgent
    from test_model_role_orchestration import formal
    from video_service.model_role_tool import RoleToolBridge
    from video_service.postgres.model_roles import ModelRoles

    runtime, owner, command = formal(db, admin, movie, tmp_path)
    roles = ModelRoles(runtime)
    speech = roles.enroll(owner, command)
    roles.publish_exact(owner, command["run_id"], command["attempt_id"], lambda _: True)
    agent = TranscriptionAgent(
        tmp_path / "speech",
        lambda *_: [{"start": 0.1, "end": 0.4, "text": "Controlled input"}],
    )
    roles.receive(RoleReceiver(agent, runtime.store, runtime.store).deliver(speech))
    translation = roles.dispatch_next(owner, command["run_id"])
    assert translation["agent"]["id"] == "translate"
    envelope = roles.enroll(owner, translation)
    assert envelope["role"] == "translation"
    assert not any(
        k in canonical(envelope) for k in [b"credential_ref", b"endpoint", b"owner_id"]
    )
    roles.publish_exact(
        owner, translation["run_id"], translation["attempt_id"], lambda _: True
    )
    provider = []

    def respond(request):
        provider.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '["통제 번역 응답"]'}]},
                    }
                ]
            },
        )

    runtime.translation_runtime.transport_factory = lambda: httpx.MockTransport(respond)
    bridge = RoleToolBridge(roles, chunk_concurrency=1)

    def tool(task, batch, candidate):
        from mideagent_models.cli import translation_packet

        return bridge.invoke_translation(translation_packet(task, batch, candidate))

    translator = TranslationAgent(tmp_path / "translator", tool)
    ack = RoleReceiver(
        translator, runtime.store, runtime.store, tool_mode="nonpaid-controlled"
    ).deliver(envelope)
    done = roles.receive(ack)
    row = next(r for r in done["runs"] if r["id"] == translation["attempt_id"])
    assert (
        row["status"] == "completed"
        and row["result"]["transport"] == "independent_model_role"
    )
    result = json.loads(
        runtime.store.read(owner, row["result"]["outputs"]["transcript"])
    )
    original = json.loads(
        runtime.store.read(owner, translation["inputs"]["transcript"])
    )
    assert result[0]["text"] == "통제 번역 응답"
    assert [{k: v for k, v in r.items() if k != "text"} for r in result] == [
        {k: v for k, v in r.items() if k != "text"} for r in original
    ]
    assert len(provider) == 1
    with db.connection() as c:
        assert (
            c.execute(
                "SELECT count(*)n FROM agent_deliveries WHERE node_run_id=%s",
                (translation["attempt_id"],),
            ).fetchone()["n"]
            == 0
        )
    assert roles.receive(ack)["id"] == done["id"] and len(provider) == 1


def test_fresh_job_explicitly_enrolls_both_roles_without_changing_old_jobs(
    db, admin, movie, tmp_path
):
    from types import SimpleNamespace

    from test_model_role_orchestration import formal
    from video_service.model_role_coordinator import ModelRoleCoordinator

    runtime, owner, job = formal(db, admin, movie, tmp_path, prepare=False)
    factory = SimpleNamespace(
        model_role_factory=lambda: None,
        model_role_factories={
            "transcription": lambda: None,
            "translation": lambda: None,
        },
    )
    service = ModelRoleCoordinator(runtime, factory)
    result = service.enroll_job(
        owner,
        job["id"],
        job["revision"],
        "explicit-both",
        roles=["transcription", "translation"],
    )
    assert result["roles"] == ["transcription", "translation"]
    assert service.enrolled(runtime, owner, job["id"], role="translation")
    assert service.inspect(owner, job["id"])["enrolled_roles"] == [
        "transcription",
        "translation",
    ]
