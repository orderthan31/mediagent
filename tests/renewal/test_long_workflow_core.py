"""Renewal formal-ticket basic whole workflow. Controlled replies, not model quality.

This core subprocess test is NOT the independent MQ/installed-process acceptance.
"""

import base64
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import video_service.postgres as pg
from test_audio_batches import wav
from test_foundation import admin as _admin
from test_original_upload_policy import db as _db
from video_service.audio_contract import audio_info
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db = _admin, _db


@pytest.mark.parametrize(
    "mode", ["complete", "cancel_between_chunks", "dense_count", "dense_bytes"]
)
def test_saved_editor_full_workflow_reaches_batched_asr_translation_both_subtitles_and_playable_video(
    db, admin, tmp_path, mode
):
    # Explicit new-goal preview dependency in this disposable schema only.
    preview = Path(pg.__file__).parent / "migrations" / "020_video_preview_jobs.sql"
    with db.connection() as fixture:
        raw = preview.read_bytes()
        fixture.execute(raw.decode())
        fixture.execute(
            "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
            (preview.name, hashlib.sha256(raw).hexdigest()),
        )
    definition = json.loads(
        Path(os.environ["MIDEAGENT_FRONTEND_TEMPLATE_FILE"]).read_text()
    )
    definition_id = definition.pop("id")
    owner = admin[0]["id"]
    registry, credentials = Registry(db), CredentialStore(db, secrets.token_bytes(32))
    cid, mid = uuid4().hex, uuid4().hex
    connection = registry.save_connection(
        owner,
        cid,
        revision=0,
        name="isolated long workflow peer",
        provider="openai_compatible",
        protocol="gemini",
        endpoint="http://127.0.0.1:9111/v1",
    )
    connection = credentials.save(
        owner, cid, revision=connection["revision"], secret=secrets.token_urlsafe(32)
    )
    registry.save_model(
        owner,
        mid,
        revision=0,
        name="controlled Gemini timed/text",
        model="gemini-3.8-flash",
        connection_id=cid,
        connection_revision=connection["current_revision"],
        model_types=["multimodal", "speech_recognition", "text"],
        input_modalities=["audio", "text"],
        output_modalities=["text"],
        capabilities=["speech_recognition", "structured_output", "text_generation"],
    )
    for node in definition["nodes"]:
        if node["type"] in {"transcribe", "translate"}:
            node["model_ref"] = {"model_id": mid, "revision": 1}
    calls = []

    def provider(request):
        body = json.loads(request.content)
        first = body["contents"][0]["parts"][0]
        with db.connection() as observer:
            assert (
                observer.execute(
                    "SELECT count(*) AS count FROM model_chunk_attempts WHERE owner_id=%s AND status='started'",
                    (owner,),
                ).fetchone()["count"]
                == 1
            )
        if "inlineData" in first:
            kind = "transcription"
            raw = base64.b64decode(first["inlineData"]["data"])
            duration = audio_info(raw)["duration_seconds"]
            count = 100 if mode == "dense_count" else 40 if mode == "dense_bytes" else 1
            text = json.dumps(
                [
                    {
                        "start": index * duration / count,
                        "end": duration
                        if index + 1 == count
                        else (index + 1) * duration / count,
                        "text": (
                            "source words " * 20
                            if mode == "dense_bytes"
                            else "controlled source "
                        )
                        + str(index),
                    }
                    for index in range(count)
                ]
            )
        else:
            kind = "translation"
            values = json.loads(first["text"])
            assert len(values) <= 100
            assert len(first["text"].encode("utf-8")) <= 16000
            text = json.dumps(["translated " + value for value in values])
        calls.append(kind)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}
                ]
            },
        )

    factory = lambda: httpx.MockTransport(provider)
    kwargs = {
        "transport_factory": factory,
        "approved_origins": {"http://127.0.0.1:9111"},
        "mode": "controlled_http",
    }
    store_root = tmp_path / "cas"
    store_root.mkdir()
    runtime = Execution(
        db,
        ContentStore(store_root),
        transcription_runtime=TranscriptionRuntime(credentials, **kwargs),
        translation_runtime=TranslationRuntime(credentials, **kwargs),
    )
    saved = runtime.save_definition(owner, definition_id, definition)
    source_audio = tmp_path / "long.wav"
    source_audio.write_bytes(wav(121))
    movie = tmp_path / "long-source.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=5:d=121",
            "-i",
            str(source_audio),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(movie),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    original = runtime.ingest(owner, movie.name, movie.read_bytes())
    ticket = runtime.create(
        owner,
        original["asset_id"],
        saved["id"],
        saved["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    plan = runtime.plan(owner, ticket["id"])
    assert plan["ready"], plan["reasons"]
    consent = runtime.confirm(owner, ticket["id"], plan["token"], uuid4().hex)
    runtime.admit(owner, ticket["id"], consent["id"], uuid4().hex)
    cancelled_once = []
    if mode == "cancel_between_chunks":
        batch_runtime = runtime.transcription_runtime.transcribe_batched

        def stop_after_committed_chunk(*args, **kwargs):
            original_record = kwargs["record"]

            def record_and_cancel(progress):
                original_record(progress)
                if (
                    not cancelled_once
                    and progress
                    and progress[-1].get("status") == "completed"
                ):
                    cancelled_once.append(True)
                    current = runtime.get(owner, ticket["id"])
                    runtime.cancel(owner, ticket["id"], current["revision"])

            kwargs["record"] = record_and_cancel
            return batch_runtime(*args, **kwargs)

        runtime.transcription_runtime.transcribe_batched = stop_after_committed_chunk
    for _ in range(30):
        command = runtime.claim_next(owner, ticket["id"])
        if command is None:
            break
        result = runtime.execute_command(owner, command)
        runtime.accept(owner, command, result)
    done = runtime.get(owner, ticket["id"])
    if mode == "cancel_between_chunks":
        original_ticket = ticket["id"]
        assert done["status"] == "cancelled" and calls == ["transcription"]
        assert not any(row["node_type"] == "translate" for row in done["runs"])
        ticket = runtime.recover(
            owner, original_ticket, uuid4().hex, acknowledge_duplicate_risk=True
        )
        retry_plan = runtime.plan(owner, ticket["id"])
        assert retry_plan["ready"], retry_plan["reasons"]
        retry_consent = runtime.confirm(
            owner, ticket["id"], retry_plan["token"], uuid4().hex
        )
        runtime.admit(owner, ticket["id"], retry_consent["id"], uuid4().hex)
        for _ in range(30):
            command = runtime.claim_next(owner, ticket["id"])
            if command is None:
                break
            response = runtime.execute_command(owner, command)
            runtime.accept(owner, command, response)
        done = runtime.get(owner, ticket["id"])
        resumed_asr = next(
            row for row in done["runs"] if row["node_type"] == "transcribe"
        )
        assert resumed_asr["result"]["transcription"]["reused_chunks"] == 1
        assert resumed_asr["result"]["transcription"]["call_count"] == 2
        assert runtime.get(owner, original_ticket)["status"] == "cancelled"
    assert done["status"] == "completed", [
        (row["node_type"], row["status"]) for row in done["runs"]
    ]
    assert calls[:3] == ["transcription"] * 3 and all(
        kind == "translation" for kind in calls[3:]
    )
    asr = next(row for row in done["runs"] if row["node_type"] == "transcribe")
    translated = next(row for row in done["runs"] if row["node_type"] == "translate")
    source = json.loads(
        runtime.store.read(owner, asr["result"]["outputs"]["transcript"])
    )
    output = json.loads(
        runtime.store.read(owner, translated["result"]["outputs"]["transcript"])
    )
    assert [(row["start"], row["end"]) for row in output] == [
        (row["start"], row["end"]) for row in source
    ]
    assert output[-1]["end"] == 121
    assert [row["id"] for row in output] == [row["id"] for row in source]
    from video_service.transcript_batches import split_transcript

    expected_batches = list(split_transcript(source))
    assert calls == ["transcription"] * 3 + ["translation"] * len(expected_batches)
    assert len(translated["result"]["translation"]["chunks"]) == len(expected_batches)
    if mode in {"dense_count", "dense_bytes"}:
        assert len(expected_batches) > 1
    subtitles = [row for row in done["runs"] if row["node_type"] == "generate_subtitle"]
    assert len(subtitles) == 2 and all(
        runtime.store.read(owner, row["result"]["outputs"]["subtitles"])
        for row in subtitles
    )
    assert all("sami" in row["result"]["outputs"] for row in subtitles), (
        "both original and translated SAMI are real separate results, not SRT relabels"
    )
    assert all(
        b"<SAMI>" in runtime.store.read(owner, row["result"]["outputs"]["sami"])
        for row in subtitles
    )
    encoded = next(row for row in done["runs"] if row["node_type"] == "encode")[
        "result"
    ]["outputs"]["video"]
    video_path = runtime.store.path(owner, encoded)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert abs(float(json.loads(probe.stdout)["format"]["duration"]) - 121) <= 0.1
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video_path), "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=30,
    )

    from app.renewal import create_app
    from fastapi.testclient import TestClient

    app = create_app(
        db,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
        credential_store=credentials,
    )
    with TestClient(app, base_url="https://testserver") as browser:
        login = browser.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
            headers={"Origin": "https://testserver"},
        )
        assert login.status_code == 200
        for row in subtitles:
            download = browser.get(
                "/api/renewal/jobs/"
                + ticket["id"]
                + "/artifacts/"
                + row["id"]
                + "/sami?download=true"
            )
            assert download.status_code == 200
            assert download.headers["content-disposition"].endswith('.smi"')
            assert download.content == runtime.store.read(
                owner, row["result"]["outputs"]["sami"]
            )
