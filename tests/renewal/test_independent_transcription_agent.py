import importlib.util
import wave

import pytest


def audio(path, seconds=2):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\0\0" * (16000 * seconds))
    return path


def implementation():
    assert importlib.util.find_spec("mideagent_models") is not None, (
        "independent model agent package missing"
    )
    from mideagent_models.transcription import TranscriptionAgent

    return TranscriptionAgent


def request(path, task="a" * 32, max_calls=4):
    import hashlib

    return {
        "version": 1,
        "task_id": task,
        "role": "transcription",
        "audio": {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        },
        "model": {"model_id": "b" * 32, "revision": 1},
        "source_language": "auto",
        "chunk_frames": 16000,
        "max_calls": max_calls,
        "timeline": [
            {"packed_start": 0, "packed_end": 2, "source_start": 10, "source_end": 12}
        ],
    }


def test_role_graph_owns_checkpoint_and_accepts_all_silence(tmp_path):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    calls = []

    def tool(model, raw, language):
        calls.append(len(raw))
        return []

    agent = Agent(tmp_path / "state", tool)
    result = agent.run(request(movie), movie)
    assert result["status"] == "completed" and result["segments"] == []
    assert len(calls) == 2
    assert {
        "prepare",
        "acquire",
        "invoke",
        "validate",
        "advance",
        "finish",
        "hold",
        "cancelled",
    } <= set(agent.graph_nodes())
    assert agent.checkpoint(request(movie)["task_id"])["status"] == "completed"
    again = Agent(tmp_path / "state", tool).run(request(movie), movie)
    assert again == result and len(calls) == 2


def test_role_preserves_overlapping_speakers(tmp_path):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    task = request(movie)
    task["chunk_frames"] = 32000
    agent = Agent(
        tmp_path / "state",
        lambda *_: [
            {"start": 0, "end": 1, "text": "A", "speaker": "one"},
            {"start": 0.5, "end": 1.5, "text": "B", "speaker": "two"},
        ],
    )
    result = agent.run(task, movie)
    assert [(r["start"], r["end"], r["speaker"]) for r in result["segments"]] == [
        (10, 11, "one"),
        (10.5, 11.5, "two"),
    ]


def test_role_unknown_restart_reuses_completed_chunk_without_recalling_unknown(
    tmp_path,
):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    calls = []

    def tool(*_):
        calls.append(1)
        if len(calls) == 2:
            raise TimeoutError("controlled response loss")
        return []

    agent = Agent(tmp_path / "state", tool)
    one = agent.run(request(movie), movie)
    assert one["status"] == "held" and one["completed_chunks"] == 1 and len(calls) == 2
    two = Agent(tmp_path / "state", tool).run(request(movie), movie)
    assert two["status"] == "held" and two["completed_chunks"] == 1 and len(calls) == 2


def test_role_cancel_before_run_starts_no_model_call(tmp_path):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    calls = []
    a = Agent(tmp_path / "state", lambda *_: calls.append(1))
    a.prepare_task(request(movie), movie)
    a.cancel("a" * 32)
    result = a.run(request(movie), movie)
    assert result["status"] == "cancelled" and calls == []


def test_cached_audio_cannot_replace_verified_source_pcm(tmp_path):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    calls = []
    a = Agent(tmp_path / "state", lambda *_: calls.append(1) or [])
    a.prepare_task(request(movie), movie)
    chunk = tmp_path / "state" / ("a" * 32) / "000000.wav"
    chunk.write_bytes(b"not the verified PCM")
    with pytest.raises(ValueError, match="chunk_cache_mismatch"):
        a.run(request(movie), movie)
    assert calls == []


def test_chunk_parallelism_is_configured_independently_of_total_call_budget(tmp_path):
    import threading

    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    barrier = threading.Barrier(2)

    def tool(*_):
        barrier.wait(timeout=3)
        return []

    agent = Agent(tmp_path / "state", tool, chunk_concurrency=2)
    result = agent.run(request(movie, max_calls=2), movie)
    assert result["status"] == "completed" and result["model_calls"] == 2


def test_invalid_task_identity_never_opens_a_lock_outside_role_state(tmp_path):
    Agent = implementation()
    movie = audio(tmp_path / "a.wav")
    task = request(movie)
    task["task_id"] = "../escape"
    agent = Agent(tmp_path / "state", lambda *_: [])
    with pytest.raises(ValueError):
        agent.run(task, movie)
    assert not (tmp_path / "escape.execution.lock").exists()


def test_one_role_instance_shares_call_concurrency_across_simultaneous_tasks(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    Agent = implementation()
    wav = audio(tmp_path / "a.wav", seconds=1)
    ready = threading.Barrier(2)
    second = threading.Event()
    guard = threading.Lock()
    stats = {"active": 0, "peak": 0, "calls": 0}

    class SynchronizedAgent(Agent):
        def _acquire(self, state):
            value = super()._acquire(state)
            if value["status"] == "ready":
                ready.wait(timeout=3)
            return value

    def tool(*args):
        with guard:
            stats["calls"] += 1
            ordinal = stats["calls"]
            stats["active"] += 1
            stats["peak"] = max(stats["peak"], stats["active"])
        if ordinal == 1:
            second.wait(timeout=1)
        else:
            second.set()
        with guard:
            stats["active"] -= 1
        return []

    agent = SynchronizedAgent(tmp_path / "state", tool, chunk_concurrency=1)
    packets = []
    for identity in ["a" * 32, "c" * 32]:
        packet = request(wav, task=identity, max_calls=1)
        packet["timeline"] = [
            {"packed_start": 0, "packed_end": 1, "source_start": 10, "source_end": 11}
        ]
        packets.append(packet)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda packet: agent.run(packet, wav), packets))
    assert all(result["status"] == "completed" for result in results)
    assert stats == {"active": 0, "peak": 1, "calls": 2}


def test_total_call_budget_is_not_raised_by_larger_admin_concurrency(tmp_path):
    Agent = implementation()
    wav = audio(tmp_path / "a.wav")
    calls = []
    agent = Agent(
        tmp_path / "state", lambda *_: calls.append(1) or [], chunk_concurrency=7
    )
    result = agent.run(request(wav, max_calls=1), wav)
    assert result["status"] == "held" and result["model_calls"] == 0 and calls == []
