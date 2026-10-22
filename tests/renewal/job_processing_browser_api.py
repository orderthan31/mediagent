"""Disposable browser bridge: genuine ASGI API/auth/PG/files; no operating calls.

Serve only inside a disposable container published on host loopback. The private
control token is a test-only injection boundary, never mounted by app.server.
"""

import json
import os
import secrets
import signal
import threading
import tempfile
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient
from app.renewal import create_app
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.content_store import ContentStore
from test_job_processing_review import uncertain, original_rows

assert os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
origin = os.environ["REVIEW_ORIGIN"]
assert urlsplit(origin).hostname == "127.0.0.1"
root = Path(tempfile.mkdtemp(prefix="job-processing-review-"))
output = Path("/evidence")
private = Path("/private")
schema = "job_review_browser_" + uuid4().hex
with psycopg.connect(os.environ["MIDEAGENT_TEST_DSN"]) as c:
    c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
db = Database(
    make_conninfo(os.environ["MIDEAGENT_TEST_DSN"], options="-c search_path=" + schema)
)
db.migrate()
password = secrets.token_urlsafe(24)
actor = Accounts(db).create("processing-review-admin", password, first=True)
content = root / "content"
content.mkdir(mode=0o700)
runtime = Execution(db, ContentStore(content))
video = root / "synthetic.mp4"
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=160x90:r=5:d=0.6",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=0.6",
        "-threads",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(video),
    ],
    check=True,
    capture_output=True,
)
fixtures = {}
original = {}
for name, execute in [("hold", False), ("stale", True), ("recover", True)]:
    job, command, result = uncertain(
        runtime, actor["id"], video.read_bytes(), execute=execute
    )
    original[name] = original_rows(runtime, job["id"])
    runtime.get(actor["id"], job["id"])
    fixtures[name] = {"id": job["id"], "command": command, "result": result}
    if name == "recover":
        runtime.accept(actor["id"], command, result)
app = create_app(
    db,
    allowed_origins=(origin, "http://testserver"),
    secure_cookies=False,
    content_store=runtime.store,
    local_execution=True,
)
control = secrets.token_urlsafe(32)
(private / "browser-config.json").write_text(
    json.dumps(
        {
            "origin": origin,
            "username": actor["username"],
            "password": password,
            "control": control,
            "jobs": {k: v["id"] for k, v in fixtures.items()},
        }
    )
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_request(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        if self.path.startswith("/__fixture/"):
            if self.headers.get("X-Fixture-Control") != control:
                self.send_error(403)
                return
            action = self.path.split("/")[-1]
            if action == "late":
                data = json.loads(body)
                case = fixtures[data["case"]]
                runtime.accept(actor["id"], case["command"], case["result"])
                value = {"injected": True}
            elif action == "readback":
                with db.connection() as c:
                    value = {
                        "scope": "isolated genuine API/browser with local synthetic FFmpeg; no physical worker/MQ claim",
                        "parents_unchanged": {
                            name: original_rows(runtime, v["id"]) == original[name]
                            for name, v in fixtures.items()
                        },
                        "decisions": [
                            dict(r)
                            for r in c.execute(
                                "SELECT id,actor_id,choice,reason,child_id FROM job_processing_decisions ORDER BY created_at,id"
                            ).fetchall()
                        ],
                        "late_results": c.execute(
                            "SELECT count(*) n FROM job_processing_late_results"
                        ).fetchone()["n"],
                        "children": [
                            dict(r)
                            for r in c.execute(
                                "SELECT id,parent_id,status,snapshot_sha256 FROM jobs WHERE parent_id IS NOT NULL"
                            ).fetchall()
                        ],
                    }
                (output / "browser-db-readback.json").write_text(
                    json.dumps(value, indent=2)
                )
                value = {"recorded": True, **value}
            else:
                self.send_error(404)
                return
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path.startswith("/api/"):
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection")
            }
            with TestClient(app) as client:
                response = client.request(
                    self.command, self.path, headers=headers, content=body
                )
            self.send_response(response.status_code)
            for k, v in response.headers.multi_items():
                if k.lower() not in (
                    "transfer-encoding",
                    "content-length",
                    "connection",
                ):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
            return
        path = Path("/src/apps/web/dist") / self.path.split("?")[0].lstrip("/")
        if not path.is_file():
            path = Path("/src/apps/web/dist/index.html")
        if not path.resolve().is_relative_to(Path("/src/apps/web/dist").resolve()):
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            {
                ".js": "text/javascript",
                ".css": "text/css",
                ".png": "image/png",
                ".svg": "image/svg+xml",
            }.get(path.suffix, "text/html"),
        )
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request


server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(
        sig, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start()
    )
print(
    json.dumps({"ready": True, "scope": "isolated-job-processing-review"}), flush=True
)
try:
    server.serve_forever()
finally:
    server.server_close()
    with psycopg.connect(os.environ["MIDEAGENT_TEST_DSN"]) as c:
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
