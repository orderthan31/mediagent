"""Existing temporary worker authority may expire; each new I/O gets a task-bound lease."""

import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from test_execution import admin as _admin
from test_execution import db as _db
from test_execution import movie as _movie
from test_model_role_user_connection import setup_api, start_user_role
from video_service.cpu_agents import digest
from video_service.object_store import S3ContentStore
from video_service.postgres.model_roles import ModelRoles

db, admin, movie = _db, _admin, _movie


def test_expired_bootstrap_keys_are_not_used_for_task_input_or_later_output(
    db, admin, movie, tmp_path
):
    assert importlib.util.find_spec("video_service.role_storage_leases") is not None, (
        "task-scoped storage lease issuer missing"
    )
    from mideagent_models.storage import TaskLeasedStore
    from video_service.role_storage_leases import RoleStorageLeases

    runtime, owner, job, client, _factory, commands, *_ = setup_api(
        db, admin, movie, tmp_path
    )
    start_user_role(runtime, owner, job, client)
    packet = commands[0]
    keys = json.loads(Path("/fixture/private/operator.json").read_text())
    sts = boto3.client(
        "sts",
        endpoint_url="https://model-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=keys["object_user"],
        aws_secret_access_key=keys["object_password"],
        verify="/fixture/private/ca.pem",
        config=Config(
            signature_version="s3v4", retries={"total_max_attempts": 1}, proxies={}
        ),
    )
    cache = tmp_path / "outputs"
    cache.mkdir()
    outputs = S3ContentStore(
        runtime.store.client,
        "model-role-boundary",
        cache,
        prefix="lease-proof-transcription",
    )
    policies = []

    def mint(policy):
        policies.append(policy)
        return sts.assume_role(
            RoleArn="arn:aws:iam::000000000000:role/independent-transcription",
            RoleSessionName="isolated-storage-lease",
            DurationSeconds=900,
            Policy=json.dumps(policy),
        )["Credentials"]

    issuer = RoleStorageLeases(
        ModelRoles(runtime, result_store=outputs), "transcription", issuer=mint
    )

    class Tool:
        def storage_lease(self, payload):
            return issuer.grant(payload)

    def cfg(prefix, folder):
        folder.mkdir()
        return {
            "endpoint": "https://model-objects:9000",
            "bucket": "model-role-boundary",
            "region": "us-east-1",
            "prefix": prefix,
            "cache_root": str(folder),
            "access_key_env": "DEAD_ACCESS",
            "secret_key_env": "DEAD_SECRET",
            "session_token_env": "DEAD_SESSION",
            "ca_file": "/fixture/private/ca.pem",
        }

    reader = TaskLeasedStore(cfg("inputs", tmp_path / "leased-input"), Tool())
    writer = TaskLeasedStore(
        cfg("lease-proof-transcription", tmp_path / "leased-output"), Tool()
    )
    reader.bind_delivery(packet, "result")
    writer.bind_delivery(packet, "result")
    source = packet["source"]
    path = reader.path(source["owner"], source["reference"])
    assert path.stat().st_size == source["reference"]["bytes"]
    result = writer.put(
        owner, [b"new result after an arbitrarily long model run"], "metadata"
    )
    assert (
        writer.read(owner, result) == b"new result after an arbitrarily long model run"
    )
    assert len(policies) == 3 and policies[0]["Statement"][0]["Action"] == [
        "s3:GetObject"
    ]
    assert policies[0]["Statement"][0]["Resource"] == [
        "arn:aws:s3:::model-role-boundary/inputs/"
        + source["owner"]
        + "/"
        + source["reference"]["storage_key"]
    ]
    with pytest.raises(ValueError):
        RoleStorageLeases(
            ModelRoles(runtime, result_store=outputs), "vocalization", issuer=mint
        ).grant(
            {
                "task_id": packet["task"]["task_id"],
                "request_sha256": digest(packet),
                "kind": "result",
            }
        )
    with db.connection() as c:
        assert (
            c.execute("SELECT count(*)n FROM model_role_tool_calls").fetchone()["n"]
            == 0
        )


def test_held_delivery_is_not_recalled_or_dropped_and_does_not_consume_an_execution_slot():
    from mideagent_models.broker import preserve_held_delivery

    class Channel:
        def basic_qos(self, **kw):
            self.qos = kw

    channel = Channel()
    active = [(42, None, "result")]
    held = set()
    preserve_held_delivery(channel, active, active[0], held, slots=1)
    assert active == [] and held == {42} and channel.qos == {"prefetch_count": 2}
