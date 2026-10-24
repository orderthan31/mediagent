"""Versioned real CPU export, retaining legacy SRT and adding SAMI."""

import hashlib
from uuid import uuid4

from video_service.cpu_agents import canonical, run


def test_v3_subtitle_export_emits_original_srt_and_separate_real_sami_without_widening_v1(
    tmp_path,
):
    root = tmp_path
    (root / "blobs").mkdir()
    (root / "outputs").mkdir()
    source = canonical(
        [
            {"start": 0.1, "end": 2, "text": "first <literal>"},
            {"start": 3, "end": 5, "text": "second line"},
        ]
    )
    sha = hashlib.sha256(source).hexdigest()
    (root / "blobs" / sha).write_bytes(source)
    command = {
        "protocol_version": 1,
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "generation": 1,
        "agent": {"id": "generate_subtitle", "revision": "3"},
        "inputs": {
            "transcript": {
                "storage_key": "blobs/" + sha,
                "sha256": sha,
                "bytes": len(source),
                "type": "transcript",
            }
        },
        "options": {"format": "srt_smi", "language": "ko"},
    }
    result = run(command, root, root / "outputs", agent="generate_subtitle")
    assert result["status"] == "completed"
    assert set(result["outputs"]) == {"subtitles", "sami"}
    from video_service.rabbitmq_transport import validate_result

    wire = {
        **result,
        "transport": "s3_subprocess",
        "outputs": {
            name: {**ref, "storage_key": "blobs/" + ref["sha256"]}
            for name, ref in result["outputs"].items()
        },
    }
    validate_result(command, wire)
    sami = (root / "outputs" / result["outputs"]["sami"]["storage_key"]).read_text()
    srt = (root / "outputs" / result["outputs"]["subtitles"]["storage_key"]).read_text()
    assert "<SAMI>" in sami and '<SYNC Start="100">' in sami and "lang: ko" in sami
    assert "&lt;literal&gt;" in sami and "00:00:00,100 --> 00:00:02,000" in srt
    old = {
        **command,
        "attempt_id": uuid4().hex,
        "agent": {"id": "generate_subtitle", "revision": "1"},
        "options": {},
    }
    legacy = run(old, root, root / "outputs", agent="generate_subtitle")
    assert legacy["status"] == "completed" and set(legacy["outputs"]) == {"subtitles"}
