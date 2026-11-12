"""Explicit opt-in local graph checks; no DB, provider, network or model runtime.

Run this file explicitly once LangGraph/checkpoint dependencies and the runtime's
file-lock implementation are available. Missing dependencies are failures, not skips.
"""
import hashlib
import io
import json
import wave

import pytest

from video_service.canonical import canonical


def private_content_store(tmp_path):
    from video_service.content_store import ContentStore

    root = tmp_path / "content"
    root.mkdir()
    return ContentStore(root)


def translation_case(tmp_path, rows):
    from mideagent_agents.translation.model_graph import TranslationAgent

    raw = canonical(rows)
    path = tmp_path / "source.json"
    path.write_bytes(raw)
    task = {"version": 2, "role_policy_version": 2, "role": "translation", "task_id": "a" * 32,
            "transcript": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "models": [{"model_id": model * 32, "revision": 1, "pin_sha256": model * 64} for model in ("b", "c")],
            "source_language": "en", "target_language": "ko", "batch_policy": "bounded_100x16k_v1", "max_calls": 2}
    return TranslationAgent, task, path


def test_empty_translation_finishes_with_no_calls_and_duplicate_delivery_is_stable(tmp_path):
    from mideagent_model_runtime.broker import RoleReceiver

    Agent, task, _ = translation_case(tmp_path, [])
    store = private_content_store(tmp_path)
    owner = "d" * 32
    source = store.put(owner, [canonical([])], "transcript")
    calls = []
    agent = Agent(tmp_path / "state", lambda *_: calls.append(1))
    receiver = RoleReceiver(agent, store, store)
    envelope = {"version": 1, "role": "translation", "task": task, "source": {"owner": owner, "reference": source}, "output_owner": owner}
    delivered = receiver.deliver(envelope)
    assert receiver.deliver(envelope) == delivered
    result = json.loads(store.read(owner, delivered["result_ref"], limit=16 * 1024 * 1024))["result"]
    assert result["status"] == "completed"
    assert result["segments"] == result["chunks"] == []
    assert result["model_calls"] == result["completed_chunks"] == 0
    assert result["selected"] is None and calls == []


@pytest.mark.parametrize("cancel_first", [True, False])
def test_empty_translation_cancel_and_finish_keep_the_atomic_winner(tmp_path, cancel_first):
    Agent, task, path = translation_case(tmp_path, [])
    agent = Agent(tmp_path / "state", lambda *_: pytest.fail("silent input cannot invoke"))
    agent.prepare_task(task, path)
    if cancel_first:
        agent.cancel(task["task_id"])
    result = agent.run(task, path)
    assert result["status"] == ("cancelled" if cancel_first else "completed")
    assert agent.cancel(task["task_id"])["status"] == result["status"]
    assert result["model_calls"] == 0


@pytest.mark.parametrize("capacity", [False, True])
def test_expansion_or_capacity_revalidation_never_spends_on_second_candidate(tmp_path, capacity):
    rows = [{"id": 7, "start": 0, "end": 1, "text": "Hi", "speaker": "A"}]
    Agent, task, path = translation_case(tmp_path, rows)
    calls = []
    text = "한" * (23000 if capacity else 7000)

    def tool(task, batch, candidate):
        calls.append(candidate)
        return {"status": "received", "reply": json.dumps([text], ensure_ascii=False)}

    agent = Agent(tmp_path / "state", tool)
    result = agent.run(task, path)
    assert result["status"] == ("held" if capacity else "completed")
    if capacity:
        assert result["held_reason"] == "translation_output_capacity"
        row = agent.state.chunk(task["task_id"], 0)
        assert row["status"] == "received" and row["reply"]
    else:
        assert result["segments"] == [{**rows[0], "text": text}]
    assert agent.run(task, path) == result
    assert calls == [0] and result["model_calls"] == 1


def speech_case(tmp_path, *, count=2, cap=2):
    from mideagent_agents.transcription.model_graph import TranscriptionAgent

    raw = io.BytesIO()
    with wave.open(raw, "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(b"\0\0" * 16000)
    raw = raw.getvalue()
    path = tmp_path / "source.wav"
    path.write_bytes(raw)
    task = {"version": 2, "role_policy_version": 2, "role": "transcription", "task_id": "a" * 32,
            "audio": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "models": [{"model_id": model * 32, "revision": 1, "pin_sha256": model * 64} for model in ("b", "c")[:count]],
            "source_language": "en", "chunk_frames": 16000, "max_calls": cap,
            "timeline": [{"packed_start": 0, "packed_end": 1, "source_start": 3, "source_end": 4}]}
    return TranscriptionAgent, task, path


def test_asr_definitive_a_failure_then_b_success_records_actual_model_and_reuses(tmp_path):
    from mideagent_model_tools.endpoints import EndpointFailure

    Agent, task, path = speech_case(tmp_path)
    calls = []

    def tool(model, *_):
        calls.append(model)
        if model == task["models"][0]:
            raise EndpointFailure("fixture", code="unavailable")
        return []

    agent = Agent(tmp_path / "state", tool)
    result = agent.run(task, path)
    assert result["status"] == "completed" and result["model_calls"] == 2
    assert result["chunks"][0]["candidate_index"] == 1
    assert result["chunks"][0]["model"] == task["models"][1]
    assert agent.run(task, path) == result and calls == task["models"]


@pytest.mark.parametrize("count,cap,expected_calls", [(2, 2, 2), (1, 2, 1), (2, 1, 1)])
def test_asr_all_fail_no_fallback_or_exhausted_cap_stops_without_refund(tmp_path, count, cap, expected_calls):
    from mideagent_model_tools.endpoints import EndpointFailure

    Agent, task, path = speech_case(tmp_path, count=count, cap=cap)
    calls = []

    def tool(*_):
        calls.append(1)
        raise EndpointFailure("fixture", code="rate_limited")

    agent = Agent(tmp_path / "state", tool)
    result = agent.run(task, path)
    assert result["status"] == "held" and result["model_calls"] == expected_calls
    assert agent.run(task, path)["status"] == "held"
    assert len(calls) == expected_calls


@pytest.mark.parametrize("prior", ["started", "unknown", "completed", "auth", "rejected"])
def test_asr_existing_or_ineligible_first_candidate_blocks_second_without_call(tmp_path, prior):
    Agent, task, path = speech_case(tmp_path)
    agent = Agent(tmp_path / "state", lambda *_: pytest.fail("cannot bypass existing attempt"))
    agent.prepare_task(task, path)
    assert agent.state.reserve(task["task_id"], 0) == "reserved"
    if prior == "completed":
        agent.state.reply(task["task_id"], 0, [])
        agent.state.complete(task["task_id"], 0, [])
    elif prior == "unknown":
        agent.state.fail(task["task_id"], 0, "outcome_unknown", True)
    elif prior in {"auth", "rejected"}:
        agent.state.candidate_failed(task["task_id"], 0, prior)
    result = agent.run(task, path)
    assert result["status"] == ("completed" if prior == "completed" else "held")
    assert result["model_calls"] == 1
    assert agent.state.chunk(task["task_id"], 1) is None
