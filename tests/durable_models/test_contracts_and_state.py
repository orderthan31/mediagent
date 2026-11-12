import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from mideagent_agents.state import RoleState
from mideagent_model_runtime.cli import speech_context, translation_packet
from video_service.canonical import canonical, digest
from video_service.role_policy import model_binding, tool_context
from video_service.role_task_contracts import InvalidRoleDelivery, validate
from video_service.transcript_batches import TranscriptBatch


def speech_envelope():
    task = {"version": 1, "role": "transcription", "task_id": "a" * 32,
            "audio": {"sha256": "c" * 64, "bytes": 32044},
            "model": {"model_id": "b" * 32, "revision": 1}, "source_language": "en",
            "chunk_frames": 16000, "max_calls": 2,
            "timeline": [{"packed_start": 0, "packed_end": 1, "source_start": 3, "source_end": 4}]}
    return {"version": 1, "role": "transcription", "task": task,
            "source": {"owner": "d" * 32, "reference": {**task["audio"], "storage_key": "blobs/" + "c" * 64, "type": "audio"}},
            "output_owner": "d" * 32}


def test_legacy_fixed_task_bytes_and_single_model_schema():
    envelope = speech_envelope()
    task = envelope["task"]
    expected = ('{"audio":{"bytes":32044,"sha256":"' + "c" * 64 +
                '"},"chunk_frames":16000,"max_calls":2,"model":{"model_id":"' + "b" * 32 +
                '","revision":1},"role":"transcription","source_language":"en","task_id":"' + "a" * 32 +
                '","timeline":[{"packed_end":1,"packed_start":0,"source_end":4,"source_start":3}],"version":1}').encode()
    assert canonical(validate(envelope, "result")["task"]) == expected
    assert digest(task) == hashlib.sha256(expected).hexdigest()
    assert speech_context(task, {"index": 3}) == {"task_id": "a" * 32, "chunk_index": 3}
    task["models"] = [task.pop("model")]
    with pytest.raises(InvalidRoleDelivery):
        validate(envelope, "result")


def test_legacy_translation_packet_bytes_have_no_policy_context():
    task = {"version": 1, "task_id": "a" * 32, "models": [{"model_id": "b" * 32, "revision": 1}]}
    packet = translation_packet(task, TranscriptBatch(0, 0, 1, [], "c" * 64), 0)
    expected = ('{"batch_index":0,"candidate_index":0,"input_sha256":"' + "c" * 64 +
                '","model":{"model_id":"' + "b" * 32 + '","revision":1},"task_id":"' + "a" * 32 + '"}').encode()
    assert canonical(packet) == expected
    assert digest(packet) == hashlib.sha256(expected).hexdigest()


def test_v2_task_and_tool_context_bind_full_frozen_pin_and_policy():
    envelope = speech_envelope()
    task = envelope["task"]
    pin = {"model_id": "b" * 32, "revision": 1, "connection_revision": 4, "inference": {"temperature": 0}}
    task.update(version=2, role_policy_version=2, models=[model_binding(pin)])
    del task["model"]
    assert validate(envelope, "result") == envelope
    assert speech_context(task, {"index": 3}, 0) == {**tool_context(task), "task_id": task["task_id"], "chunk_index": 3, "candidate_index": 0}
    for bad in [None, True, -1, 1, "0"]:
        with pytest.raises(ValueError):
            speech_context(task, {"index": 3}, bad)
    changed = deepcopy(pin)
    changed["inference"]["temperature"] = 1
    assert model_binding(changed) != task["models"][0]
    changed_task = {**task, "role_policy_version": 1}
    assert digest(changed_task) != tool_context(task)["task_sha256"]


def test_local_sqlite_attempt_cap_survives_failure_reuse_and_concurrency(tmp_path):
    state = RoleState(tmp_path)
    task = {"role": "transcription", "max_calls": 2}
    state.ensure("a" * 32, digest(task), task)
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda i: state.reserve("a" * 32, i), range(4)))
    assert statuses.count("reserved") == 2
    assert statuses.count("budget_exhausted") == 2
    started = [i for i, status in enumerate(statuses) if status == "reserved"]
    state.candidate_failed("a" * 32, started[0], "rate_limited")
    state.reply("a" * 32, started[1], [])
    state.complete("a" * 32, started[1], [])
    assert state.reserve("a" * 32, started[1]) == "completed"
    assert state.reserve("a" * 32, 5) == "budget_exhausted"
    assert state.task("a" * 32)["calls"] == 2


@pytest.mark.parametrize("cancel_first", [True, False])
def test_local_sqlite_empty_completion_and_cancel_have_one_winner(tmp_path, cancel_first):
    state = RoleState(tmp_path)
    task = {"role": "translation", "max_calls": 2}
    identity = "a" * 32
    state.ensure(identity, digest(task), task)
    completed = {"version": 1, "task_id": identity, "role": "translation", "status": "completed",
                 "segments": [], "chunks": [], "completed_chunks": 0, "model_calls": 0, "selected": None}
    if cancel_first:
        with state.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            state.cancel_in(c, identity)
    result = state.finish(identity, completed)
    with state.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        cancelled = state.cancel_in(c, identity)
    expected = "cancelled" if cancel_first else "completed"
    assert result["status"] == cancelled["status"] == expected
    assert state.finish(identity, completed) == result
    assert json.loads(state.task(identity)["result"]) == result
    assert state.task(identity)["calls"] == 0
