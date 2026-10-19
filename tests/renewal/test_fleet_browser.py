"""Real production-bundle browser acceptance for administrator CPU fleet controls."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from test_execution import movie as _movie_fixture
from test_foundation import db as _db_fixture

db = _db_fixture
movie = _movie_fixture


@pytest.mark.skipif(
    os.environ.get("MIDEAGENT_FLEET_BROWSER") != "1",
    reason="Explicit fleet browser opt-in required",
)
def test_real_admin_fleet_and_ordinary_job_browser(db, movie, tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    synthetic = tmp_path / "synthetic.mp4"
    synthetic.write_bytes(movie)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    evidence = Path(os.environ["MIDEAGENT_FLEET_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "FLEET_TEST_DSN": db.dsn,
        "MIDEAGENT_TEST_ORIGIN": origin,
        "MIDEAGENT_TEST_MOVIE": str(synthetic),
    }
    root = Path(__file__).resolve().parents[2]
    with (evidence / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.renewal_server",
                "--dsn-env",
                "FLEET_TEST_DSN",
                "--content-root",
                str(content),
                "--origin",
                origin,
                "--allow-cpu",
                "--manage-cpu",
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError(
                        "Isolated fleet server exited; inspect private server.log"
                    )
                try:
                    if (
                        httpx.get(origin + "/api/auth/session", timeout=1).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Isolated fleet server did not become ready")
            result = subprocess.run(
                ["node", str(root / "tests/renewal/frontend-fleet.mjs")],
                check=False,
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=160,
            )
            (evidence / "browser.log").write_text(result.stdout + result.stderr)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            process.terminate()
            process.wait(timeout=20)
