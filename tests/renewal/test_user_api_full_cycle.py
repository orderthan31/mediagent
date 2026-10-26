import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from test_execution import admit
from test_packed_projection_execution import projection_wire as _wire
from test_vocalization_execution import admin as _admin
from test_vocalization_execution import db as _db
from test_vocalization_execution import movie as _movie
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db, movie, projection_wire = _admin, _db, _movie, _wire


def test_actual_user_api_graph_two_review_gates_and_cpu_downloads(
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
            name="isolated subtitle tracks",
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
            name="controlled subtitle tracks",
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
        translation_runtime=TranslationRuntime(credentials, **kwargs),
        transcription_runtime=TranscriptionRuntime(credentials, **kwargs),
    )
    graph = json.loads(Path(__file__).with_name("user_api_full_cycle.json").read_text())
    for n in graph["nodes"]:
        if n["type"] in {"transcribe", "translate"}:
            n["model_ref"] = refs[0 if n["type"] == "transcribe" else 1]
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    inspection = runtime.inspect(owner, definition["id"], definition["revision"])
    for item in inspection["summary"]:
        if item["type"] in {"transcribe", "translate"}:
            assert item["model_required"] is True
            assert item["model"]["name"] == "controlled subtitle tracks"
            assert item["model_ref"]["revision"] == 1
    asset = runtime.ingest(owner, "isolated-short-real-media.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "auto", "target_language": "ko"},
    )
    admit(runtime, owner, job["id"])
    first = runtime.run_local(owner, job["id"])
    assert first["status"] == "review_required", first
    assert calls.count("translation") == 0
    review = first["reviews"][0]
    assert review["contract"]["type"] == "transcript"
    saved = runtime.review_save(
        owner, review["id"], review["revision"], {"approved": True}
    )
    runtime.review_confirm(owner, review["id"], saved["revision"])
    admit(runtime, owner, job["id"])
    second = runtime.run_local(owner, job["id"])
    assert second["status"] == "review_required", second
    review = next(r for r in second["reviews"] if r["status"] == "draft")
    assert review["contract"]["kind"] == "subtitle_tracks_v1"
    saved = runtime.review_save(
        owner, review["id"], review["revision"], {**review["draft"], "approved": True}
    )
    runtime.review_confirm(owner, review["id"], saved["revision"])
    prior = json.loads(json.dumps(calls))
    cpu = Execution(db, runtime.store)
    admit(cpu, owner, job["id"])
    done = cpu.run_local(owner, job["id"])
    assert done["status"] == "completed", done
    assert calls == prior
    outputs = [r for r in done["runs"] if r["node_type"] == "encode"]
    assert len(outputs) == 2
    from app.renewal import create_app
    from fastapi.testclient import TestClient

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
        for r in outputs:
            response = client.get(
                "/api/renewal/jobs/"
                + job["id"]
                + "/artifacts/"
                + r["id"]
                + "/video?download=true"
            )
            assert response.status_code == 200
            assert (
                hashlib.sha256(response.content).hexdigest()
                == r["result"]["outputs"]["video"]["sha256"]
            )
    from video_service.postgres.subtitle_tracks import SubtitleTracks

    exports = SubtitleTracks(cpu).outputs(job["id"])
    assert len(exports["outputs"]) == 1
    assert (
        sum(len(track["files"]) for track in exports["outputs"][0]["tracks"].values())
        == 4
    )
