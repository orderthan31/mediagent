import json

import pytest
from test_independent_transcription_agent import audio, implementation, request


@pytest.mark.parametrize("order", ["cancel_before_commit", "cancel_after_commit"])
def test_cancel_and_completion_have_one_atomic_authoritative_winner(
    tmp_path, monkeypatch, order
):
    import mideagent_models.transcription as speech

    Agent = implementation()
    wav = audio(tmp_path / "a.wav")
    task = request(wav)
    calls = []
    acks = []
    agent = Agent(tmp_path / "state", lambda *_: calls.append(1) or [])
    real = speech.project
    if order == "cancel_before_commit":

        def at_projection(*args, **kwargs):
            acks.append(agent.cancel(task["task_id"]))
            return real(*args, **kwargs)

        monkeypatch.setattr(speech, "project", at_projection)
    result = agent.run(task, wav)
    if order == "cancel_after_commit":
        acks.append(agent.cancel(task["task_id"]))
    row = agent.state.task(task["task_id"])
    expected = "cancelled" if order == "cancel_before_commit" else "completed"
    assert result["status"] == expected
    assert row["status"] == expected and bool(row["cancelled"]) == (
        expected == "cancelled"
    )
    assert json.loads(row["result"]) == result
    assert acks[0]["status"] == expected
    assert ("projection_trace" in result) == (expected == "completed")
    assert len(calls) == 2


def test_first_completion_commit_survives_actual_process_exit_with_trace(tmp_path):
    import subprocess
    import sys

    Agent = implementation()
    wav = audio(tmp_path / "a.wav")
    task = request(wav)
    packet = tmp_path / "task.json"
    packet.write_text(json.dumps(task))
    calls = tmp_path / "calls.txt"
    script = r"""import json,os,sys
from pathlib import Path
from mideagent_models.transcription import TranscriptionAgent
root,wav,packet,calls=map(Path,sys.argv[1:])
def tool(*args):
    with calls.open('a')as f:f.write('call\n');f.flush();os.fsync(f.fileno())
    return []
a=TranscriptionAgent(root,tool);original=a.state.finish
def crash(task,result):
    committed=original(task,result)
    if committed['status']=='completed':os._exit(97)
    return committed
a.state.finish=crash
a.run(json.loads(packet.read_text()),wav)
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "state"),
            str(wav),
            str(packet),
            str(calls),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 97, process.stderr[-500:]

    def forbidden(*args):
        pytest.fail("completed chunk was called again")

    agent = Agent(tmp_path / "state", forbidden)
    result = agent.run(task, wav)
    assert result["status"] == "completed" and "projection_trace" in result
    assert json.loads(agent.state.task(task["task_id"])["result"]) == result
    assert calls.read_text().splitlines() == ["call", "call"]


@pytest.mark.parametrize(
    "clock",
    [
        [],
        [{"packed_start": 0, "packed_end": 1, "source_start": 10, "source_end": 11}],
        [{"packed_start": 0, "packed_end": 2, "source_start": 10, "source_end": 11}],
        [
            {
                "packed_start": 0,
                "packed_end": 1.9999375,
                "source_start": 10,
                "source_end": 11.9999375,
            }
        ],
    ],
)
def test_invalid_clock_is_rejected_before_call_and_task_admission(tmp_path, clock):
    Agent = implementation()
    wav = audio(tmp_path / "a.wav")
    task = request(wav)
    task["timeline"] = clock
    calls = []
    agent = Agent(tmp_path / "state", lambda *_: calls.append(1) or [])
    with pytest.raises(ValueError, match="clock"):
        agent.run(task, wav)
    assert calls == []
    with agent.state.connect() as connection:
        assert connection.execute("SELECT count(*)FROM tasks").fetchone()[0] == 0
