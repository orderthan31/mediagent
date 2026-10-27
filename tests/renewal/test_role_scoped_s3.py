import json
import os
from pathlib import Path

from video_service.object_store import from_config


def test_role_uses_only_temporary_s3_principal_for_verified_input_and_own_output(
    tmp_path,
):
    descriptor = json.loads(Path("/fixture-input.json").read_text())
    owner = descriptor["owner"]
    for folder in ["input", "output"]:
        (tmp_path / folder).mkdir()
    config = {
        "endpoint": "https://model-objects:9000",
        "bucket": "model-role-boundary",
        "region": "us-east-1",
        "prefix": "inputs",
        "cache_root": str(tmp_path / "input"),
        "access_key_env": "ROLE_S3_ACCESS",
        "secret_key_env": "ROLE_S3_SECRET",
        "session_token_env": "ROLE_S3_SESSION",
        "ca_file": "/certs/ca.pem",
    }
    store = from_config(config)
    audio = store.path(owner, descriptor["reference"])
    assert audio.read_bytes().startswith(b"RIFF")
    output = from_config(
        {**config, "prefix": "transcription", "cache_root": str(tmp_path / "output")}
    )
    ref = output.put(owner, [b"[]"], "transcript")
    assert output.path(owner, ref).read_bytes() == b"[]"
    assert not any(
        k in os.environ
        for k in ["PG_DSN", "DATABASE_URL", "MINIO_ROOT_PASSWORD", "MASTER_KEY"]
    )


def test_role_receives_only_self_contained_artifacts_and_publishes_own_result(tmp_path):
    import importlib.util

    assert importlib.util.find_spec("mideagent_models.broker") is not None, (
        "independent role receiver missing"
    )
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent

    descriptor = json.loads(Path("/fixture-input.json").read_text())
    owner = descriptor["owner"]
    reference = descriptor["reference"]
    for name in ["input", "output"]:
        (tmp_path / name).mkdir()
    config = {
        "endpoint": "https://model-objects:9000",
        "bucket": "model-role-boundary",
        "region": "us-east-1",
        "prefix": "inputs",
        "cache_root": str(tmp_path / "input"),
        "access_key_env": "ROLE_S3_ACCESS",
        "secret_key_env": "ROLE_S3_SECRET",
        "session_token_env": "ROLE_S3_SESSION",
        "ca_file": "/certs/ca.pem",
    }
    inputs = from_config(config)
    outputs = from_config(
        {**config, "prefix": "transcription", "cache_root": str(tmp_path / "output")}
    )
    calls = []
    agent = TranscriptionAgent(
        tmp_path / "state", lambda *_: calls.append(1) or [], chunk_concurrency=2
    )
    task = {
        "version": 1,
        "task_id": "c" * 32,
        "role": "transcription",
        "audio": {"sha256": reference["sha256"], "bytes": reference["bytes"]},
        "model": {"model_id": "b" * 32, "revision": 1},
        "source_language": "auto",
        "chunk_frames": 16000,
        "max_calls": 2,
        "timeline": [
            {"packed_start": 0, "packed_end": 1, "source_start": 10, "source_end": 11},
            {"packed_start": 1, "packed_end": 2, "source_start": 20, "source_end": 21},
        ],
    }
    packet = {
        "version": 1,
        "role": "transcription",
        "task": task,
        "source": descriptor,
        "output_owner": owner,
    }
    receiver = RoleReceiver(agent, inputs, outputs)
    one = receiver.receive(packet)
    two = receiver.receive(packet)
    assert one == two and one["status"] == "completed" and len(calls) == 2
    payload = json.loads(outputs.path(owner, one["result_ref"]).read_bytes())
    assert (
        payload["result"]["segments"] == []
        and payload["task"]["timeline"] == task["timeline"]
    )
    assert not {"job_id", "outbox", "next_node"} & set(packet)


def test_request_scoped_mq_cancellation_can_arrive_before_role_input(tmp_path):
    import hashlib

    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent
    from video_service.cpu_agents import canonical

    descriptor = json.loads(Path("/fixture-input.json").read_text())
    owner = descriptor["owner"]
    ref = descriptor["reference"]
    for folder in ["input", "output"]:
        (tmp_path / folder).mkdir()
    config = {
        "endpoint": "https://model-objects:9000",
        "bucket": "model-role-boundary",
        "region": "us-east-1",
        "prefix": "inputs",
        "cache_root": str(tmp_path / "input"),
        "access_key_env": "ROLE_S3_ACCESS",
        "secret_key_env": "ROLE_S3_SECRET",
        "session_token_env": "ROLE_S3_SESSION",
        "ca_file": "/certs/ca.pem",
    }
    calls = []
    agent = TranscriptionAgent(tmp_path / "state", lambda *_: calls.append(1) or [])
    receiver = RoleReceiver(
        agent,
        from_config(config),
        from_config(
            {
                **config,
                "prefix": "transcription",
                "cache_root": str(tmp_path / "output"),
            }
        ),
    )
    task = {
        "version": 1,
        "task_id": "8" * 32,
        "role": "transcription",
        "audio": {"sha256": ref["sha256"], "bytes": ref["bytes"]},
        "model": {"model_id": "b" * 32, "revision": 1},
        "source_language": "auto",
        "chunk_frames": 16000,
        "max_calls": 2,
        "timeline": [
            {"packed_start": 0, "packed_end": 2, "source_start": 10, "source_end": 12}
        ],
    }
    packet = {
        "version": 1,
        "role": "transcription",
        "task": task,
        "source": descriptor,
        "output_owner": owner,
    }
    digest = hashlib.sha256(canonical(packet)).hexdigest()
    ack = receiver.cancel(
        {
            "version": 1,
            "role": "transcription",
            "task_id": task["task_id"],
            "request_sha256": digest,
        }
    )
    result = receiver.receive(packet)
    assert ack["status"] == result["status"] == "cancelled" and calls == []
    assert agent.state.task(task["task_id"])["cancelled"] == 1


def test_cancel_protocol_does_not_coerce_boolean_version_to_integer(tmp_path):
    import pytest
    from mideagent_models.broker import RoleReceiver
    from mideagent_models.transcription import TranscriptionAgent

    agent = TranscriptionAgent(tmp_path / "state", lambda *_: [])
    receiver = RoleReceiver(agent, None, None)
    with pytest.raises(ValueError):
        receiver.cancel(
            {
                "version": True,
                "role": "transcription",
                "task_id": "5" * 32,
                "request_sha256": "0" * 64,
            }
        )
    with agent.state.connect() as connection:
        assert (
            connection.execute("SELECT count(*)FROM role_cancellations").fetchone()[0]
            == 0
        )
