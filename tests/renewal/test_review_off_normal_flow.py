"""Explicit review-OFF graph, real CPU subtitles/videos and authenticated downloads."""

import hashlib
import json
import os
from uuid import uuid4

import httpx
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_execution import admin as _admin
from test_execution import admit
from test_execution import db as _db
from test_execution import movie as _movie
from test_packed_projection_execution import projection_wire as _wire
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

db, admin, movie, projection_wire = _db, _admin, _movie, _wire


def test_review_off_saved_reopened_to_cpu_videos_and_authenticated_downloads(
    db, admin, movie, tmp_path, projection_wire
):
    owner = admin[0]["id"]
    origin, calls = projection_wire
    credentials = CredentialStore(db, os.urandom(32))
    refs = []
    for speech in [True, False]:
        cid, mid = uuid4().hex, uuid4().hex
        connection = Registry(db).save_connection(
            owner,
            cid,
            revision=0,
            name="NONPAID controlled review-OFF check",
            provider="openai_compatible",
            protocol="gemini",
            endpoint=origin + "/v1",
        )
        connection = credentials.save(
            owner, cid, revision=connection["revision"], secret=uuid4().hex
        )
        Registry(db).save_model(
            owner,
            mid,
            revision=0,
            name="NONPAID controlled response",
            model="gemini-2.5-flash",
            connection_id=cid,
            connection_revision=connection["current_revision"],
            model_types=["speech_recognition" if speech else "text"],
            input_modalities=["audio" if speech else "text"],
            output_modalities=["text"],
            capabilities=["speech_recognition" if speech else "text_generation"],
        )
        refs.append({"model_id": mid, "revision": 1})
    kwargs = {
        "transport_factory": lambda: httpx.HTTPTransport(retries=0),
        "approved_origins": {origin},
        "mode": "controlled_http",
    }
    runtime = Execution(
        db,
        ContentStore(tmp_path),
        transcription_runtime=TranscriptionRuntime(credentials, **kwargs),
        translation_runtime=TranslationRuntime(credentials, **kwargs),
    )
    graph = audio_graph(*refs)
    graph["nodes"][3]["options"].update(
        translation_profile="language_target_v1",
        target_language="ko",
        batch_policy="bounded_100x16k_v1",
        max_model_calls="1",
    )
    graph["nodes"].extend(
        [
            {
                "id": "tracks",
                "type": "subtitle_tracks",
                "options": {"original_language": "en", "translated_language": "ko"},
                "position": {"x": 1400, "y": 0},
            },
            {
                "id": "files",
                "type": "subtitle_outputs",
                "options": {"format": "srt_smi", "review_policy": "off"},
                "position": {"x": 1600, "y": 0},
            },
        ]
    )
    links = [
        ("asr", "transcript", "tracks", "original"),
        ("translate", "transcript", "tracks", "translated"),
        ("tracks", "tracks", "files", "tracks"),
    ]
    for index, track in enumerate(["original", "translated"]):
        pick, encode, validate = (
            "pick" + str(index),
            "encode" + str(index),
            "validate" + str(index),
        )
        graph["nodes"].extend(
            [
                {
                    "id": pick,
                    "type": "subtitle_track",
                    "options": {"track": track, "review_policy": "off"},
                    "position": {"x": 1800, "y": index * 250},
                },
                {
                    "id": encode,
                    "type": "encode",
                    "options": {"subtitle_mode": "burn", "video_codec": "h264"},
                    "position": {"x": 2000, "y": index * 250},
                },
                {
                    "id": validate,
                    "type": "validate_video",
                    "options": {},
                    "position": {"x": 2200, "y": index * 250},
                },
            ]
        )
        links.extend(
            [
                ("files", "manifest", pick, "manifest"),
                (pick, "subtitles", encode, "subtitles"),
                ("$input", "video", encode, "video"),
                (encode, "video", validate, "video"),
            ]
        )
    graph["edges"].extend(
        {
            "id": uuid4().hex,
            "source": {"node": a, "port": b},
            "target": {"node": c, "port": d},
        }
        for a, b, c, d in links
    )
    from video_service.renewal_contracts import validate

    assert validate(graph)["valid"], validate(graph)
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    reopened = runtime.definition(owner, definition["id"])
    assert reopened["nodes"] == definition["nodes"]
    asset = runtime.ingest(owner, "NONPAID-connection-check.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    assert done["status"] == "completed", done
    assert done["reviews"] == [] and calls == ["transcription", "translation"]
    manifest_run = next(r for r in done["runs"] if r["node_id"] == "files")
    manifest = json.loads(
        runtime.store.read(owner, manifest_run["result"]["outputs"]["manifest"])
    )
    assert manifest["review"] is None and manifest["review_policy"] == "off"
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app) as client:
        assert client.get("/api/renewal/jobs/" + job["id"]).status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                json={"username": admin[0]["username"], "password": admin[1]},
            ).status_code
            == 200
        )
        for row in done["runs"]:
            if row["node_type"] in {"encode", "subtitle_outputs"}:
                for name, ref in row["result"]["outputs"].items():
                    response = client.get(
                        "/api/renewal/jobs/"
                        + job["id"]
                        + "/artifacts/"
                        + row["id"]
                        + "/"
                        + name
                        + "?download=true"
                    )
                    assert response.status_code == 200
                    assert hashlib.sha256(response.content).hexdigest() == ref["sha256"]
