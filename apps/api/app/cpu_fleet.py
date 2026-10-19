"""Explicitly owned persistent CPU processes. Does not discover Docker or a queue."""

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time

from video_service.cpu_agents import CPU_AGENTS, canonical


class CpuProcesses:
    runtime = "cpu_subprocess"

    def __init__(self, content_store, *, python=None):
        if getattr(content_store, "storage_kind", None) != "local":
            raise ValueError(
                "Local CPU instances require an explicit private local store"
            )
        self.store = content_store
        self.python = python or sys.executable
        self.processes = {}
        self.locks = {}
        self.guard = threading.RLock()

    def supports(self, agent):
        return agent in CPU_AGENTS

    @staticmethod
    def _line(process, timeout):
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        # Use unbuffered pipes; select must not wait for bytes already buffered in Python.
        while len(buffer) <= 65536:
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or not select.select([process.stdout], [], [], remaining)[0]
            ):
                raise TimeoutError("CPU instance response timeout")
            block = os.read(process.stdout.fileno(), 1)
            if not block:
                raise OSError("CPU instance disconnected")
            if block == b"\n":
                return json.loads(buffer)
            buffer.extend(block)
        raise ValueError("CPU response size exceeded")

    def start(self, identity, agent):
        if not self.supports(agent):
            raise ValueError("CPU runtime unavailable for this agent")
        environment = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "PATH",
                "LANG",
                "HOME",
                "TMPDIR",
                "PYTHONPATH",
                "FONTCONFIG_PATH",
            )
        }
        process = subprocess.Popen(
            [
                self.python,
                "-m",
                "mideagent_cpu.server",
                "--agent",
                agent,
                "--content-root",
                str(self.store.root),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            bufsize=0,
            start_new_session=True,
        )
        with self.guard:
            self.processes[identity] = process
            self.locks[identity] = threading.Lock()
        try:
            ready = self._line(process, 8)
            if ready != {"event": "ready", "agent_id": agent, "pid": process.pid}:
                raise ValueError("CPU handshake mismatch")
            return process.pid
        except Exception:
            self.stop(identity)
            raise

    def alive(self, identity):
        process = self.processes.get(identity)
        return process is not None and process.poll() is None

    def pid(self, identity):
        process = self.processes.get(identity)
        return process.pid if process is not None and process.poll() is None else None

    def request(self, identity, owner, command):
        with self.locks[identity]:
            process = self.processes[identity]
            if process.poll() is not None:
                raise OSError("CPU instance unavailable")
            payload = canonical({"owner": owner, "command": command}) + b"\n"
            if len(payload) > 65536:
                raise ValueError("CPU envelope size exceeded")
            try:
                process.stdin.write(payload)
                process.stdin.flush()
                return self._line(process, 90)
            except (OSError, TimeoutError, ValueError):
                self.stop(identity)
                raise

    def stop(self, identity):
        process = self.processes.get(identity)
        if process is not None:
            if process.poll() is None:
                # Only the private session created by this driver; include its ffmpeg child.
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()

    def close(self):
        for identity in list(self.processes):
            self.stop(identity)
