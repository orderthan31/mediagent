import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_independent_transcription_agent import audio, request


def test_role_cli_applies_admin_chunk_concurrency_to_real_http_calls(tmp_path):
    wav = audio(tmp_path / "a.wav")
    barrier = threading.Barrier(2)
    seen = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(1)
            try:
                barrier.wait(timeout=3)
                status = 200
            except threading.BrokenBarrierError:
                status = 503
            self.send_response(status)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {
        "role": "transcription",
        "state_root": str(tmp_path / "state"),
        "tool_url": f"http://127.0.0.1:{server.server_port}/transcribe",
        "credential_env": "OWNED_ROLE_TEST_TOKEN",
        "allow_controlled_loopback": True,
        "timeout_seconds": 8,
        "chunk_concurrency": 2,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "HOME", "TMPDIR", "PYTHONPATH"}
    }
    env["OWNED_ROLE_TEST_TOKEN"] = "controlled-not-a-provider-key"
    try:
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "mideagent_models.cli",
                "--config",
                str(path),
                "--audio",
                str(wav),
            ],
            input=json.dumps(request(wav, max_calls=7)),
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert child.returncode == 0, child.stderr[-200:]
        result = json.loads(child.stdout)
        assert result["status"] == "completed" and result["model_calls"] == 2
        assert len(seen) == 2
        import sqlite3

        with sqlite3.connect(tmp_path / "state" / "role-state.sqlite") as c:
            frozen, calls = c.execute("SELECT request,calls FROM tasks").fetchone()
        assert json.loads(frozen)["max_calls"] == 7 and calls == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
