"""Exercise installed fixed-role entrypoints, not only module imports/help."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_execution import movie as _movie_fixture
from video_service.content_store import ContentStore
from video_service.cpu_agents import canonical

movie = _movie_fixture


@pytest.mark.parametrize(
    "kind",
    ["analyze", "extract_audio", "generate_subtitle", "encode", "validate_video"],
)
def test_fixed_cpu_cli(kind, movie, tmp_path):
    store = ContentStore(tmp_path)
    owner = uuid4().hex
    if kind == "generate_subtitle":
        reference = store.put(
            owner,
            [canonical([{"start": 0, "end": 0.5, "text": "Synthetic only"}])],
            "transcript",
        )
        inputs = {"transcript": reference}
    else:
        reference = store.put(owner, [movie], "video")
        inputs = {"video": reference}
    output = tmp_path / "cli-output"
    output.mkdir(mode=0o700)
    command = {
        "protocol_version": 1,
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "generation": 1,
        "agent": {"id": kind, "revision": "1"},
        "inputs": inputs,
        "options": {"subtitle_mode": "none"} if kind == "encode" else {},
    }
    executable = Path(sys.executable).parent / ("mideagent-" + kind.replace("_", "-"))
    assert executable.is_file(), "Install agents/cpu in the isolated test environment"
    result = subprocess.run(
        [
            str(executable),
            "--input-root",
            str(store.owner_root(owner)),
            "--output-root",
            str(output),
        ],
        input=canonical(command),
        capture_output=True,
        timeout=90,
        check=False,
        env={
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "LANG", "TMPDIR", "FONTCONFIG_PATH")
        },
    )
    assert result.returncode == 0, result.stdout.decode()
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "completed" and receipt["agent"]["id"] == kind
    for ref in receipt["outputs"].values():
        data = (output / ref["storage_key"]).read_bytes()
        assert (
            len(data) == ref["bytes"]
            and hashlib.sha256(data).hexdigest() == ref["sha256"]
        )
