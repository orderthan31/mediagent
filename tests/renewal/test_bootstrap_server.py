"""Exercise the real file-bootstrap deployment process against a disposable PG schema."""

import json
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from test_foundation import db as _db_fixture

db = _db_fixture


def test_file_bootstrap_server_starts_without_legacy_runtime(db, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    dsn = tmp_path / "dsn"
    dsn.write_text(db.dsn)
    dsn.chmod(0o600)
    content = tmp_path / "content"
    content.mkdir(mode=0o700)
    bootstrap = tmp_path / "api.json"
    bootstrap.write_text(
        json.dumps(
            {
                "database_dsn_file": str(dsn),
                "content_root": str(tmp_path / "content"),
                "allowed_origins": [origin],
                "host": "127.0.0.1",
                "port": port,
                "secure_cookies": False,
            }
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app.server", "--bootstrap-file", str(bootstrap)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                _, diagnostics = process.communicate(timeout=2)
                raise AssertionError(
                    diagnostics.decode(errors="replace").replace(db.dsn, "[DSN]")
                )
            try:
                with urlopen(origin + "/healthz", timeout=1) as response:
                    assert response.status == 200
                    assert json.loads(response.read())
                break
            except (URLError, TimeoutError):
                time.sleep(0.05)
        else:
            raise AssertionError("Explicit server was not ready")
        try:
            urlopen(origin + "/api/accounts", timeout=2)
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Unauthenticated management route must fail closed")
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        assert db.dsn.encode() not in stdout + stderr
