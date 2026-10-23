"""Versioned CPU video input limits do not relax other agents or outputs."""

from datetime import UTC

from video_service.rabbitmq_transport import validate_command


def command(role="validate_video", revision="2", size=300 * 1024 * 1024):
    return {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": role, "revision": revision},
        "inputs": {
            "video": {
                "type": "video",
                "bytes": size,
                "sha256": "c" * 64,
                "storage_key": "blobs/" + "c" * 64,
            }
        },
        "options": {},
    }


def test_explicit_v2_cpu_validation_accepts_large_video_reference():
    value = command()
    assert validate_command(value) == value


def test_native_v2_validation_uses_actual_media(tmp_path):
    from test_execution import movie
    from video_service.content_store import ContentStore
    from video_service.cpu_agents import run

    raw = movie.__wrapped__(tmp_path)
    (tmp_path / "input").mkdir()
    store = ContentStore(tmp_path / "input")
    owner = "d" * 32
    ref = store.put(owner, [raw], "video")
    out = tmp_path / "out"
    out.mkdir()
    value = command(size=len(raw))
    value["inputs"]["video"] = ref
    result = run(value, store.owner_root(owner), out, agent="validate_video")
    assert result["status"] == "completed"
    assert result["agent"]["revision"] == "2"


def test_source_policy_freezes_only_supported_large_cpu_workflow():
    from video_service import cpu_input_policy as policy

    row = {
        "bytes": 300 * 1024 * 1024,
        "metadata": {
            "registration_state": "verified",
            "media": {"duration": 60, "width": 160, "height": 90},
        },
    }
    definition = {
        "nodes": [{"id": "e", "type": "encode"}, {"id": "v", "type": "validate_video"}]
    }
    assert policy.source_policy(row, definition) == policy.LARGE_PROFILE


def test_large_encoder_child_output_is_bounded(tmp_path):
    import sys

    import pytest
    from video_service import cpu_agents

    target = tmp_path / "too-large.bin"
    code = (
        "from pathlib import Path;Path('too-large.bin').write_bytes(b'x'*(2*1024*1024))"
    )
    with pytest.raises(ValueError, match="budget"):
        cpu_agents.process_bounded(
            [sys.executable, "-c", code],
            output=target,
            cwd=tmp_path,
            timeout=5,
            max_bytes=1024 * 1024,
        )


def test_object_executor_v2_receipt_keeps_exact_request_and_real_output(tmp_path):
    from test_execution import movie
    from test_preserved_original_storage import Peer
    from video_service.object_agent import execute
    from video_service.object_store import S3ContentStore

    raw = movie.__wrapped__(tmp_path)
    cache = tmp_path / "remote-cache"
    cache.mkdir()
    import io

    class JsonPeer(Peer):
        def put_object(self, **kw):
            if isinstance(kw["Body"], bytes):
                kw["Body"] = io.BytesIO(kw["Body"])
            return super().put_object(**kw)

    store = S3ContentStore(JsonPeer(), "isolated", cache, prefix="bounded")
    owner = "e" * 32
    ref = store.put(owner, [raw], "video")
    value = command(size=len(raw))
    value["inputs"]["video"] = ref
    result = execute(store, owner, value, agent="validate_video")
    assert result["status"] == "completed"
    assert result["agent"] == value["agent"]
    assert execute(store, owner, value, agent="validate_video") == result


def test_v2_workspace_is_attempt_private_and_removed(tmp_path):
    from video_service import cpu_input_policy as policy

    kept = tmp_path / "keep-existing"
    kept.write_bytes(b"preserve")
    with policy.workspace(tmp_path, command()) as root:
        assert root != tmp_path and root.parent == tmp_path
        (root / "attempt-only").write_bytes(b"temporary")
    assert not root.exists() and kept.read_bytes() == b"preserve"


def test_large_preserved_source_is_selectable_for_supported_cpu_only():
    from datetime import datetime

    from video_service.postgres.intake import public_asset

    row = {
        "id": "a" * 32,
        "owner_id": "b" * 32,
        "filename": "large.mov",
        "bytes": 300 * 1024 * 1024,
        "sha256": "c" * 64,
        "created_at": datetime.now(UTC),
        "metadata": {
            "registration_state": "verified",
            "media": {"duration": 10, "width": 1920, "height": 1080},
            "legacy_origin": {"original_owner_id": None},
        },
    }
    value = public_asset(row)
    assert value["processing_supported"] is True
    assert value["processing_roles"] == ["encode", "validate_video"]
    assert value["uploaded_by"] is None


def test_new_input_ceiling_and_other_roles_remain_rejected():
    import pytest
    from video_service.rabbitmq_transport import InvalidMessage

    for value in [
        command(size=4 * 1024 * 1024 * 1024 + 1),
        command(revision="1"),
        command(role="analyze"),
    ]:
        with pytest.raises(InvalidMessage):
            validate_command(value)


def test_large_unsupported_workflow_and_metadata_are_refused():
    import pytest
    from video_service.cpu_input_policy import source_policy

    row = {
        "bytes": 300 * 1024 * 1024,
        "metadata": {
            "registration_state": "verified",
            "media": {"duration": 10, "width": 1920, "height": 1080},
        },
    }
    with pytest.raises(ValueError, match="only"):
        source_policy(row, {"nodes": [{"type": "extract_audio"}]})
    row["bytes"] = 4 * 1024 * 1024 * 1024 + 1
    with pytest.raises(ValueError, match="4 GiB"):
        source_policy(row, {"nodes": [{"type": "encode"}]})


def test_v2_parent_propagates_verified_terminal_failure_not_unknown(monkeypatch):
    import json
    import subprocess

    from video_service.cpu_agents import canonical, digest
    from video_service.object_agent import ObjectAgentExecutor

    value = command()
    result = {
        k: value[k]
        for k in ("protocol_version", "run_id", "attempt_id", "generation", "agent")
    }
    result.update(
        request_sha256=digest(value),
        status="failed",
        outputs={},
        transport="s3_subprocess",
        error={"code": "cpu_agent_failed", "retryable": False},
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 1, canonical(result), b""),
    )
    cfg = json.dumps(
        {"access_key_env": "FIXTURE_USER", "secret_key_env": "FIXTURE_SECRET"}
    )
    execute = ObjectAgentExecutor(
        "FIXTURE_CONFIG",
        environ={"FIXTURE_CONFIG": cfg, "FIXTURE_USER": "", "FIXTURE_SECRET": ""},
    )
    assert execute("d" * 32, value) == result
