"""Wire-format and source-layout regressions; synthetic shapes are not execution receipts."""

import ast
import json
import subprocess
import sys
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest
from app.server import load_bootstrap
from jsonschema import Draft202012Validator
from video_service.agent_protocol import CPU_AGENTS, schemas
from video_service.cpu_agents import digest
from video_service.node_contracts import node_spec
from video_service.rabbitmq_transport import InvalidMessage, envelope

ROOT = Path(__file__).resolve().parents[2]


def command(role):
    spec = node_spec(role)
    return {
        "protocol_version": 1,
        "run_id": "a" * 32,
        "attempt_id": "b" * 32,
        "generation": 1,
        "agent": {"id": role, "revision": "1"},
        "inputs": {
            port: {
                "storage_key": "blobs/" + "c" * 64,
                "sha256": "c" * 64,
                "bytes": 1,
                "type": kind,
            }
            for port, kind in spec["inputs"].items()
            if port not in spec["optional_inputs"]
        },
        "options": {"subtitle_mode": "none"} if role == "encode" else {},
    }


def synthetic_result(cmd):
    return {
        **{
            k: cmd[k]
            for k in ("protocol_version", "run_id", "attempt_id", "generation", "agent")
        },
        "request_sha256": digest(cmd),
        "status": "completed",
        "transport": "s3_subprocess",
        "outputs": {
            port: {
                "storage_key": "blobs/" + "d" * 64,
                "sha256": "d" * 64,
                "bytes": 1,
                "type": kind,
            }
            for port, kind in node_spec(cmd["agent"]["id"])["outputs"].items()
        },
    }


def test_packaged_wire_schemas_are_current():
    for name, schema in schemas().items():
        Draft202012Validator.check_schema(schema)
        assert (
            json.loads(files("video_service").joinpath("contracts", name).read_text())
            == schema
        )


@pytest.mark.parametrize("role", sorted(CPU_AGENTS))
def test_each_role_has_explicit_request_and_response(role):
    cmd = command(role)
    request = json.loads(envelope("e" * 32, cmd).body)
    response = json.loads(envelope("e" * 32, cmd, synthetic_result(cmd)).body)
    Draft202012Validator(schemas()["agent.command.v1.schema.json"]).validate(request)
    Draft202012Validator(schemas()["agent.result.v1.schema.json"]).validate(response)
    bad = deepcopy(cmd)
    bad["options"]["api_key"] = "synthetic-unsupported-field"
    with pytest.raises(InvalidMessage):
        envelope("e" * 32, bad)


@pytest.mark.parametrize(
    "mutation", ["extra", "bool-generation", "digest", "ports", "artifact", "type"]
)
def test_response_rejects_mismatched_or_unexpected_data(mutation):
    cmd = command("generate_subtitle")
    result = synthetic_result(cmd)
    if mutation == "extra":
        result["provider_credential"] = "synthetic-unsupported-field"
    elif mutation == "bool-generation":
        result["generation"] = True
    elif mutation == "digest":
        result["request_sha256"] = "f" * 64
    elif mutation == "ports":
        result["outputs"] = {}
    elif mutation == "type":
        result["outputs"]["subtitles"]["type"] = "video"
    else:
        result["outputs"]["subtitles"]["storage_key"] = "blobs/" + "f" * 64
    with pytest.raises(InvalidMessage, match="invalid_result"):
        envelope("e" * 32, cmd, result)


def test_failed_response_has_bounded_error_and_no_outputs():
    cmd = command("analyze")
    result = {
        **synthetic_result(cmd),
        "status": "failed",
        "outputs": {},
        "error": {"code": "cpu_agent_failed", "retryable": False},
    }
    body = json.loads(envelope("e" * 32, cmd, result).body)
    Draft202012Validator(schemas()["agent.result.v1.schema.json"]).validate(body)
    result["error"]["detail"] = "raw-sdk-diagnostics-not-allowed"
    with pytest.raises(InvalidMessage):
        envelope("e" * 32, cmd, result)


def test_flat_layout_and_optional_gpu_imports():
    assert not (ROOT / "agents/media").exists()
    assert not (ROOT / "agents/cpu/mideagent_cpu").exists()
    assert not (ROOT / "scripts").exists()
    for path in (ROOT / "packages/shared/video_service").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("media_agent")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import mideagent_gpu.facefusion, mideagent_gpu.vad; "
                "assert 'torch' not in sys.modules and 'facefusion' not in sys.modules; print('no-engine-import')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "no-engine-import"


def test_gpu_pure_helpers_without_engine():
    from mideagent_gpu.facefusion import engine_frame_number
    from mideagent_gpu.vad import retained_intervals

    assert engine_frame_number(1, "3.9.0") == 0
    assert retained_intervals([1.0] * 50, 4.0) == [(0.0, 4.0)]
    assert retained_intervals([0.0] * 50, 4.0) == [(0.0, 0.3), (3.7, 4.0)]


def test_bootstrap_files_cannot_be_application_settings(tmp_path):
    dsn = tmp_path / "dsn"
    dsn.write_text("host=127.0.0.1 dbname=synthetic_only")
    cfg = {
        "database_dsn_file": str(dsn),
        "content_root": str(tmp_path / "content"),
        "allowed_origins": ["http://127.0.0.1:8080"],
        "host": "127.0.0.1",
        "port": 8000,
        "secure_cookies": False,
    }
    path = tmp_path / "api.json"
    path.write_text(json.dumps(cfg))
    loaded, value = load_bootstrap(path)
    assert loaded == cfg and value == dsn.read_text()
    cfg["llm_api_key"] = "synthetic-rejected-field"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="^invalid_bootstrap_file$"):
        load_bootstrap(path)
