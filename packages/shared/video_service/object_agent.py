"""One DB-free CPU command using remote CAS and independent private workspace.

There is no workflow, queue polling, database connection or provider in this CLI.
The orchestrator reserves admission; the object receipt fences redelivery even
when the subprocess host/workspace changes. Unknown attempts are never retried.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from .content_store import ID
from .cpu_agents import CPU_AGENTS, canonical, digest, run
from .cpu_input_policy import command_timeout, workspace
from .object_store import ObjectStoreError, from_config


def execute(store, owner, command, *, agent):
    from .rabbitmq_transport import validate_command
    validate_command(command)
    if agent not in CPU_AGENTS or command["agent"]["id"] != agent:
        raise ObjectStoreError("Explicit CPU agent mismatch")
    if not isinstance(owner, str) or not ID.fullmatch(owner):
        raise ObjectStoreError("Invalid owner")
    previous = store.claim_attempt(owner, command)
    if previous is not None:
        if previous.get("status") == "completed":
            for reference in previous["outputs"].values():
                store.path(owner, reference)
        return previous
    root = store.owner_root(owner)
    attempts = root / "attempts"
    if attempts.is_symlink():
        raise ObjectStoreError("Symlink workspace denied")
    attempts.mkdir(mode=0o700, exist_ok=True)
    for reference in command["inputs"].values():
        store.path(owner, reference)
    result = run(command, root, attempts, agent=agent)
    if result["status"] == "completed":
        outputs = {}
        for port, reference in result["outputs"].items():
            key = reference["storage_key"]
            expected = command["run_id"] + "-" + command["attempt_id"]
            if len(key.split("/")) != 2 or key.split("/")[0] != expected:
                raise ObjectStoreError("Output attempt mismatch")
            target = attempts / key
            if target.is_symlink() or target.parent.is_symlink():
                raise ObjectStoreError("Symlink output denied")
            with target.open("rb") as stream:
                stored = store.put(
                    owner,
                    iter(lambda: stream.read(1024 * 1024), b""),
                    reference["type"],
                )
            if (
                stored["sha256"] != reference["sha256"]
                or stored["bytes"] != reference["bytes"]
            ):
                raise ObjectStoreError("Output integrity mismatch")
            outputs[port] = stored
        result["outputs"] = outputs
    result["transport"] = "s3_subprocess"
    store.finish_attempt(owner, command, result)
    return result


class ObjectAgentExecutor:
    """Explicit adapter; config names and credentials never enter command payloads."""

    def __init__(self, config_env, *, environ):
        self.config_env, self.environ = config_env, dict(environ)
        if config_env not in self.environ:
            raise ObjectStoreError("Explicit object agent config missing")
        config = json.loads(self.environ[config_env])
        fields = ("access_key_env", "secret_key_env")
        self.env = {
            k: v
            for k, v in self.environ.items()
            if k
            in (
                "PATH",
                "LANG",
                "HOME",
                "TMPDIR",
                "PYTHONPATH",
                "FONTCONFIG_PATH",
                config_env,
                *(config[f] for f in fields),
            )
        }

    def __call__(self, owner, command):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "video_service.object_agent",
                "--config-env",
                self.config_env,
                "--owner",
                owner,
                "--agent",
                command["agent"]["id"],
            ],
            input=canonical(command),
            capture_output=True,
            timeout=command_timeout(command),
            env=self.env,
            check=False,
        )
        if len(completed.stdout) > 65536:
            raise ObjectStoreError("Agent response size exceeded")
        result = json.loads(completed.stdout)
        if (completed.returncode == 1 and command["agent"]["revision"] == "2"
                and result.get("status") == "failed"):
            from .rabbitmq_transport import validate_result
            validate_result(command, result)
            return result
        if completed.returncode != 0 or result.get("request_sha256") != digest(command):
            raise ObjectStoreError(
                "Agent failed or result unknown; automatic replay denied"
            )
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=sorted(CPU_AGENTS), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--config-env", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ObjectStoreError("Command size exceeded")
        config = json.loads(os.environ[args.config_env])
        command = json.loads(raw)
        with workspace(config["cache_root"], command) as scoped:
            result = execute(
                from_config({**config, "cache_root": str(scoped)}), args.owner,
                command, agent=args.agent,
            )
        sys.stdout.buffer.write(canonical(result))
        return 0 if result["status"] == "completed" else 1
    except Exception:  # noqa: BLE001 -- protocol boundary must suppress paths/credentials in errors
        sys.stdout.write(
            '{"status":"failed","error":{"code":"object_agent_failed_or_unknown","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
