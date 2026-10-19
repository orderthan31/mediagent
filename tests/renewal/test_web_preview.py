"""Original/WebM separation and failure preservation using synthetic media only."""

import hashlib
import json
import subprocess
from unittest.mock import patch
from uuid import uuid4

from test_execution import admit, setup
from test_execution import movie as _movie_fixture
from test_execution import runtime as _runtime_fixture
from test_foundation import admin as _admin_fixture
from test_foundation import db as _db_fixture
from test_foundation import login
from video_service.postgres import Missing

# Register imported pytest fixtures without shadowing unused imports.
admin = _admin_fixture
db = _db_fixture
movie = _movie_fixture
runtime = _runtime_fixture


def test_upload_webm_original_download_and_ranges(runtime, admin, movie):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    owner = admin[0]["id"]
    source = runtime.ingest(owner, "untouched.mp4", movie)
    assert source["web_preview"]["status"] == "ready"
    ref = source["web_preview"]["reference"]
    assert ref["sha256"] != source["sha256"] and ref["type"] == "web_video"
    original = runtime.asset_path(owner, source["asset_id"])
    assert original.read_bytes() == movie
    preview = runtime.web_preview_path(owner, source["asset_id"])
    info = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name:stream=codec_name",
                "-of",
                "json",
                str(preview),
            ]
        )
    )
    assert "webm" in info["format"]["format_name"]
    assert {s["codec_name"] for s in info["streams"]} == {"vp9", "opus"}
    client = TestClient(
        create_app(
            runtime.database,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            content_store=runtime.store,
            local_execution=True,
        )
    )
    login(client, admin)
    base = "/api/videos/" + source["asset_id"]
    response = client.get(base + "/download")
    assert (
        response.content == movie
        and "attachment" in response.headers["content-disposition"]
    )
    webm = client.get(base + "/stream?download=true")
    assert (
        webm.headers["content-type"] == "video/webm"
        and ".webm" in webm.headers["content-disposition"]
    )
    assert hashlib.sha256(webm.content).hexdigest() == ref["sha256"]
    ranged = client.get(base + "/stream", headers={"Range": "bytes=0-31"})
    assert ranged.status_code == 206 and ranged.content == webm.content[:32]
    assert (
        client.get(base + "/stream", headers={"Range": "bytes=999999999-"}).status_code
        == 416
    )
    client.cookies.clear()
    assert client.get(base + "/stream").status_code == 401
    assert client.get(base + "/download").status_code == 401


def test_output_webm_is_separate_and_recovery_reuses_preview(runtime, admin, movie):
    owner = admin[0]["id"]
    _, _, job = setup(runtime, owner, movie)
    admit(runtime, owner, job["id"])
    cmd = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, cmd)
    runtime.accept(owner, cmd, result)
    state = runtime.get(owner, job["id"])
    encoded = state["runs"][0]["result"]
    assert encoded["previews"]["video"]["status"] == "ready"
    original = encoded["outputs"]["video"]
    preview = encoded["previews"]["video"]["reference"]
    assert preview["sha256"] != original["sha256"]
    assert runtime.video_preview(
        owner, job["id"], original
    ).read_bytes() == runtime.store.read(owner, preview)
    runtime.cancel(owner, job["id"], state["revision"])
    child = runtime.recover(
        owner, job["id"], uuid4().hex, acknowledge_duplicate_risk=True
    )
    assert child["runs"][0]["result"]["previews"] == encoded["previews"]
    assert runtime.video_preview(owner, child["id"], original).is_file()


def test_preview_failure_never_destroys_or_replaces_original(runtime, admin, movie):
    import pytest

    owner = admin[0]["id"]
    with patch(
        "video_service.web_preview.process",
        side_effect=ValueError("synthetic preview failure"),
    ):
        source = runtime.ingest(owner, "preserved.mp4", movie)
    assert source["content_verified"] and source["web_preview"]["status"] == "failed"
    assert runtime.asset_path(owner, source["asset_id"]).read_bytes() == movie
    with pytest.raises(Missing):
        runtime.web_preview_path(owner, source["asset_id"])
