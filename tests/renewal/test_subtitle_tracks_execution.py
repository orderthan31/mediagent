"""Actual CPU/controlled HTTP -> independently pinned language nodes -> CAS human gate -> files."""

import json
import os
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from test_execution import admin as _admin
from test_execution import admit
from test_execution import db as _db
from test_execution import movie as _movie
from test_packed_projection_execution import projection_wire as _wire
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.postgres import Conflict
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.subtitle_tracks import SubtitleTracks
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db, movie, projection_wire = _admin, _db, _movie, _wire


@pytest.fixture
def subtitle_gate(db, admin, movie, tmp_path, projection_wire):
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
    graph = audio_graph(*refs)
    graph["nodes"][3]["options"] = {
        "translation_profile": "language_target_v1",
        "target_language": "ko",
        "batch_policy": "bounded_100x16k_v1",
        "max_model_calls": "1",
    }
    links = [
        ("asr", "transcript", "tracks", "original"),
        ("translate", "transcript", "tracks", "translated"),
        ("tracks", "tracks", "review", "value"),
        ("review", "value", "files", "tracks"),
    ]
    track_options = {"original_language": "en", "translated_language": "ko"}
    for index, code in enumerate(["ja", "fr", "pt-BR", "de"], 1):
        identity = "extra" + str(index)
        graph["nodes"].append(
            {
                "id": identity,
                "type": "translate",
                "options": {
                    "translation_profile": "language_target_v1",
                    "target_language": code,
                    "batch_policy": "bounded_100x16k_v1",
                    "max_model_calls": "1",
                },
                "position": {"x": 1100, "y": index * 120},
                "model_ref": refs[1],
            }
        )
        links.extend(
            [
                ("asr", "transcript", identity, "transcript"),
                (identity, "transcript", "tracks", "additional_" + str(index)),
            ]
        )
        track_options["additional_" + str(index) + "_language"] = code
    graph["nodes"].extend(
        [
            {
                "id": "tracks",
                "type": "subtitle_tracks",
                "options": track_options,
                "position": {"x": 1400, "y": 50},
            },
            {
                "id": "review",
                "type": "review",
                "options": {
                    "data_type": "subtitle_tracks",
                    "review_kind": "subtitle_tracks_v1",
                },
                "position": {"x": 1700, "y": 50},
            },
            {
                "id": "files",
                "type": "subtitle_outputs",
                "options": {"format": "srt_smi"},
                "position": {"x": 2000, "y": 50},
            },
        ]
    )
    graph["edges"].extend(
        {
            "id": "multi" + str(i),
            "source": {"node": a, "port": b},
            "target": {"node": c, "port": d},
        }
        for i, (a, b, c, d) in enumerate(links)
    )
    from video_service.renewal_contracts import validate

    assert validate(graph)["valid"], validate(graph)
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    asset = runtime.ingest(owner, "synthetic-subtitle-tracks.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    admit(runtime, owner, job["id"])
    gate = runtime.run_local(owner, job["id"])
    assert gate["status"] == "review_required", gate
    return runtime, owner, job["id"], gate["reviews"][0], calls


def test_save_reopen_confirm_all_six_tracks_then_export_without_retranslating(
    subtitle_gate,
):
    runtime, owner, job, review, calls = subtitle_gate
    service = SubtitleTracks(runtime)
    assert calls == ["transcription"] + ["translation"] * 5
    before = deepcopy(calls)
    track = service.track(review["id"], "translated")
    assert track["language"] == "ko"
    edited = deepcopy(track["cues"])
    edited[0]["text"] = "가" * 100
    saved = service.save(owner, review["id"], review["revision"], "translated", edited)
    reopened = SubtitleTracks(Execution(runtime.database, runtime.store)).track(
        review["id"], "translated"
    )
    assert reopened["revision"] == saved["revision"] and len(reopened["cues"]) > len(
        edited
    )
    assert (
        "".join(row["text"].replace("\n", "") for row in reopened["cues"]) == "가" * 100
    )
    with pytest.raises(Conflict):
        service.save(owner, review["id"], review["revision"], "translated", edited)
    approved = runtime.review_save(
        owner, review["id"], saved["revision"], {**saved["draft"], "approved": True}
    )
    confirmed = runtime.review_confirm(owner, review["id"], approved["revision"])
    assert confirmed["status"] == "confirmed" and calls == before
    assert runtime.get(owner, job)["status"] == "review_required"
    # No model credentials/runtime are present for the explicit continuation.
    no_models = Execution(runtime.database, runtime.store)
    admit(no_models, owner, job)
    done = no_models.run_local(owner, job)
    assert done["status"] == "completed", done
    output = next(row for row in done["runs"] if row["node_id"] == "files")["result"][
        "outputs"
    ]
    manifest = json.loads(runtime.store.read(owner, output["manifest"]))
    assert set(manifest["tracks"]) == {
        "original",
        "translated",
        "translated.ja",
        "translated.fr",
        "translated.pt-BR",
        "translated.de",
    }
    assert sum(len(track["files"]) for track in manifest["tracks"].values()) == 12
    assert (
        manifest["tracks"]["translated"]["transcript"]["sha256"]
        == reopened["transcript"]["sha256"]
    )
    assert "가" in runtime.store.read(owner, output["subtitles"]).decode()
    smi = runtime.store.read(
        owner, manifest["tracks"]["translated.pt-BR"]["files"]["smi"]["reference"]
    ).decode()
    assert "lang: pt-BR;" in smi
    assert calls == before
    model_runs = [
        row for row in done["runs"] if row["node_type"] in {"transcribe", "translate"}
    ]
    assert len(model_runs) == 6
    assert {
        row["result"]["translation"]["target_language"]
        for row in model_runs
        if row["node_type"] == "translate"
    } == {"ko", "ja", "fr", "pt-BR", "de"}


def test_subtitle_api_shared_reads_owner_saves_csrf_and_narrow_body_budget(
    subtitle_gate, admin
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient
    from video_service.postgres.accounts import Accounts

    runtime, owner, _job, review, calls = subtitle_gate
    before = list(calls)
    app = create_app(
        runtime.database,
        allowed_origins=["https://testserver"],
        secure_cookies=False,
        content_store=runtime.store,
    )
    base = "/api/renewal/reviews/" + review["id"] + "/subtitle-tracks/translated"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(base).status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
            headers={"Origin": "https://testserver"},
        )
        assert login.status_code == 200
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        track = client.get(base)
        assert track.status_code == 200, track.text
        body = {"revision": review["revision"], "cues": track.json()["cues"]}
        assert (
            client.post(
                base + "/save", json=body, headers={"Origin": "https://testserver"}
            ).status_code
            == 403
        )
        saved = client.post(base + "/save", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert (
            client.post(base + "/save", json=body, headers=headers).status_code == 409
        )
        # Explicit per-track allowance does not widen the 64KiB generic JSON route.
        huge = {
            "revision": saved.json()["revision"],
            "cues": [{"start": 0, "end": 1, "text": "x" * 70000}],
        }
        assert client.post(base + "/save", json=huge, headers=headers).status_code in {
            400,
            422,
        }
        assert (
            client.post(
                "/api/renewal/reviews/" + review["id"] + "/save",
                json={
                    "revision": saved.json()["revision"],
                    "draft": {"text": "x" * 70000},
                },
                headers=headers,
            ).status_code
            == 413
        )
        assert calls == before
    password = uuid4().hex
    member = Accounts(runtime.database).create(
        "tracks" + uuid4().hex[:8], password, actor_id=owner
    )
    with TestClient(app, base_url="https://testserver") as reader:
        login = reader.post(
            "/api/auth/login",
            json={"username": member["username"], "password": password},
            headers={"Origin": "https://testserver"},
        )
        assert login.status_code == 200
        assert reader.get(base).status_code == 200
        assert reader.post(
            base + "/save",
            json=body,
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Token": login.json()["csrf_token"],
            },
        ).status_code in {403, 404}


def test_confirmation_cannot_bypass_saved_tracks_or_mutate_cancelled_job(subtitle_gate):
    from video_service.postgres import Conflict

    runtime, owner, job, review, calls = subtitle_gate
    service = SubtitleTracks(runtime)
    before = list(calls)
    with pytest.raises(Conflict):
        runtime.review_confirm(owner, review["id"], review["revision"])
    tampered = deepcopy(review["draft"])
    tampered["approved"] = True
    tampered["tracks"]["translated"] = tampered["tracks"]["original"]
    with pytest.raises(ValueError):
        runtime.review_save(owner, review["id"], review["revision"], tampered)
    state = runtime.get(owner, job)
    runtime.cancel(owner, job, state["revision"])
    with pytest.raises(Conflict):
        service.save(
            owner,
            review["id"],
            review["revision"],
            "translated",
            service.track(review["id"], "translated")["cues"],
        )
    assert calls == before
