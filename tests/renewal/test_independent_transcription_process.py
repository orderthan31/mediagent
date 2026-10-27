import base64
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_independent_transcription_agent import audio, request


def test_separate_role_process_calls_controlled_http_and_reopens_own_checkpoint(
    tmp_path,
):
    movie = audio(tmp_path / "a.wav")
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert set(value) == {"model", "source_language", "audio_base64"}
            assert base64.b64decode(value["audio_base64"]).startswith(b"RIFF")
            calls.append(value["model"])
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {
        "role": "transcription",
        "state_root": str(tmp_path / "role"),
        "tool_url": f"http://127.0.0.1:{server.server_port}/transcribe",
        "credential_env": "OWNED_ROLE_TEST_TOKEN",
        "allow_controlled_loopback": True,
        "timeout_seconds": 5,
    }
    file = tmp_path / "role.json"
    file.write_text(json.dumps(config))
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "HOME", "TMPDIR", "PYTHONPATH"}
    }
    env["OWNED_ROLE_TEST_TOKEN"] = "controlled-not-a-provider-key"
    args = [
        sys.executable,
        "-m",
        "mideagent_models.cli",
        "--config",
        str(file),
        "--audio",
        str(movie),
    ]
    try:
        results = []
        for _ in range(2):
            completed = subprocess.run(
                args,
                input=json.dumps(request(movie)),
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            assert completed.returncode == 0, completed.stderr[-500:]
            results.append(json.loads(completed.stdout))
        assert all(r["status"] == "completed" and r["segments"] == [] for r in results)
        assert len(calls) == 2
        assert (tmp_path / "role" / "graph-checkpoints.sqlite").is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_process_loss_of_provider_reply_is_held_and_never_recalled(tmp_path):
    movie = audio(tmp_path / "a.wav")
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(1)
            if len(calls) == 2:
                self.connection.close()
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {
        "role": "transcription",
        "state_root": str(tmp_path / "role"),
        "tool_url": f"http://127.0.0.1:{server.server_port}/transcribe",
        "credential_env": "OWNED_ROLE_TEST_TOKEN",
        "allow_controlled_loopback": True,
        "timeout_seconds": 5,
    }
    file = tmp_path / "role.json"
    file.write_text(json.dumps(cfg))
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "HOME", "TMPDIR", "PYTHONPATH"}
    }
    env["OWNED_ROLE_TEST_TOKEN"] = "controlled-not-a-provider-key"
    args = [
        sys.executable,
        "-m",
        "mideagent_models.cli",
        "--config",
        str(file),
        "--audio",
        str(movie),
    ]
    try:
        results = []
        for _ in range(2):
            p = subprocess.run(
                args,
                input=json.dumps(request(movie)),
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            assert p.returncode == 0, p.stderr[-200:]
            results.append(json.loads(p.stdout))
        assert all(
            r["status"] == "held" and r["completed_chunks"] == 1 for r in results
        )
        assert results[0]["agent_pid"] != results[1]["agent_pid"] and len(calls) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cancel_process_fences_next_http_call_without_global_database(tmp_path):
    import sqlite3
    import time

    movie = audio(tmp_path / "a.wav")
    calls = []
    received = threading.Event()
    release = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(1)
            received.set()
            release.wait(8)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {
        "role": "transcription",
        "state_root": str(tmp_path / "role"),
        "tool_url": f"http://127.0.0.1:{server.server_port}/transcribe",
        "credential_env": "OWNED_ROLE_TEST_TOKEN",
        "allow_controlled_loopback": True,
        "timeout_seconds": 10,
    }
    file = tmp_path / "role.json"
    file.write_text(json.dumps(cfg))
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "HOME", "TMPDIR", "PYTHONPATH"}
    }
    env["OWNED_ROLE_TEST_TOKEN"] = "controlled-not-a-provider-key"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mideagent_models.cli",
            "--config",
            str(file),
            "--audio",
            str(movie),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    child.stdin.write(json.dumps(request(movie)))
    child.stdin.close()
    child.stdin = None
    cancel = None
    try:
        assert received.wait(8)
        cancel = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mideagent_models.cli",
                "--config",
                str(file),
                "--cancel-task",
                "a" * 32,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        flagged = False
        for _ in range(100):
            with sqlite3.connect(tmp_path / "role" / "role-state.sqlite") as c:
                flagged = c.execute("SELECT cancelled FROM tasks").fetchone()[0]
            if flagged:
                break
            time.sleep(0.02)
        assert flagged
        release.set()
        cancel_out, cancel_error = cancel.communicate(timeout=12)
        out, error = child.communicate(timeout=12)
        assert cancel.returncode == 0 and child.returncode == 0, (
            cancel_error[-200:],
            error[-200:],
        )
        assert (
            json.loads(cancel_out)["status"] == "cancelled"
            and json.loads(out)["status"] == "cancelled"
        )
        assert len(calls) == 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if child.poll() is None:
            child.wait(timeout=12)
        if cancel is not None and cancel.poll() is None:
            cancel.wait(timeout=12)
