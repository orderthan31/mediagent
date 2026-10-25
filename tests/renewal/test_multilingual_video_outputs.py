"""Reviewed multilingual tracks to real CPU video output; controlled models, no provider/GPU quality claim."""

import hashlib
import json
import os
import subprocess
from uuid import uuid4

import httpx
import pytest
from test_execution import admit
from test_packed_projection_execution import projection_wire as _wire
from test_transcription_execution import audio_graph
from test_vocalization_execution import admin as _admin
from test_vocalization_execution import db as _db
from test_vocalization_execution import movie as _movie
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.subtitle_tracks import SubtitleTracks
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db = _admin, _db


@pytest.fixture
def long_media(request):
    return getattr(request, "param", False)


@pytest.fixture
def movie(tmp_path, long_media):
    if not long_media:
        return _movie.__wrapped__(tmp_path)
    target = tmp_path / "synthetic-long-321.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=1:d=321",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=321",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return target.read_bytes()


@pytest.fixture
def projection_wire(request, long_media):
    if long_media:
        return request.getfixturevalue("long_wire")
    return request.getfixturevalue("short_wire")


short_wire = _wire


@pytest.fixture
def video_gate(db, admin, movie, tmp_path, projection_wire, long_media):
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
    for index, track in enumerate(
        [
            "original",
            "translated",
            "translated.ja",
            "translated.fr",
            "translated.pt-BR",
            "translated.de",
        ]
    ):
        choose = "pick_" + str(index)
        encode = "encode_" + str(index)
        validate_video = "validate_" + str(index)
        graph["nodes"].extend(
            [
                {
                    "id": choose,
                    "type": "subtitle_track",
                    "options": {"track": track},
                    "position": {"x": 2200, "y": index * 180},
                },
                {
                    "id": encode,
                    "type": "encode",
                    "options": {
                        "subtitle_mode": "burn",
                        "video_codec": "h264",
                        "resolution": "original",
                        "quality_profile": "balanced",
                    },
                    "position": {"x": 2500, "y": index * 180},
                },
                {
                    "id": validate_video,
                    "type": "validate_video",
                    "options": {},
                    "position": {"x": 2800, "y": index * 180},
                },
            ]
        )
        for a, b, c, d in [
            ("files", "manifest", choose, "manifest"),
            (choose, "subtitles", encode, "subtitles"),
            ("$input", "video", encode, "video"),
            (encode, "video", validate_video, "video"),
        ]:
            graph["edges"].append(
                {
                    "id": uuid4().hex,
                    "source": {"node": a, "port": b},
                    "target": {"node": c, "port": d},
                }
            )
    if long_media:
        for item in graph["nodes"]:
            if item["type"] == "extract_audio":
                item["options"] = {"media_budget": "audio_long_v5"}
            elif item["type"] == "preprocess_audio":
                item["options"] = {
                    "media_budget": "audio_long_v5",
                    "processing_profile": "regions_long_v5",
                    "audio_filter": "off",
                    "vad_mode": "off",
                }
            elif item["type"] == "transcribe":
                item["options"] = {
                    "media_budget": "audio_long_v5",
                    "clock_policy": "packed_projection_v5",
                    "batch_policy": "bounded_60s_v1",
                    "max_model_calls": "8",
                }
            elif item["type"] == "translate":
                item["options"].update(
                    media_budget="audio_long_v5", max_model_calls="8"
                )
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


@pytest.mark.parametrize("long_media", [False, True], indirect=True)
def test_six_reviewed_tracks_select_their_exact_subtitle_and_render_downloadable_cpu_videos(
    video_gate, admin, long_media
):
    from app.renewal import create_app
    from fastapi.testclient import TestClient

    runtime, owner, identity, review, calls = video_gate
    saved = runtime.review_save(
        owner, review["id"], review["revision"], {**review["draft"], "approved": True}
    )
    runtime.review_confirm(owner, review["id"], saved["revision"])
    prior = list(calls)
    cpu = Execution(runtime.database, runtime.store)
    admit(cpu, owner, identity)
    done = cpu.run_local(owner, identity)
    assert done["status"] == "completed", done
    files = next(row for row in done["runs"] if row["node_id"] == "files")["result"][
        "outputs"
    ]["manifest"]
    manifest = json.loads(cpu.store.read(owner, files))
    outputs = [row for row in done["runs"] if row["node_type"] == "encode"]
    assert len(outputs) == 6 and calls == prior
    if long_media:
        assert sum(c["stage"] == "asr" for c in calls) == 6
        assert sum(c["stage"] == "translation" for c in calls) == 10
        asr = next(row for row in done["runs"] if row["node_type"] == "transcribe")
        assert asr["result"]["transcription"]["call_count"] == 6
    for report in [r for r in done["runs"] if r["node_type"] == "validate_video"]:
        doc = json.loads(cpu.store.read(owner, report["result"]["outputs"]["report"]))
        assert abs(doc["media"]["duration"] - (321 if long_media else 0.6)) < 1

    for row in done["runs"]:
        if row["node_type"] == "subtitle_track":
            assert (
                row["result"]["outputs"]["subtitles"]
                == manifest["tracks"][row["options"]["track"]]["files"]["srt"][
                    "reference"
                ]
            )
    app = create_app(
        runtime.database,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
    )
    with TestClient(app) as client:
        assert client.get("/api/renewal/jobs/" + identity).status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": admin[0]["username"], "password": admin[1]},
        )
        assert login.status_code == 200
        for row in outputs:
            response = client.get(
                "/api/renewal/jobs/"
                + identity
                + "/artifacts/"
                + row["id"]
                + "/video?download=true"
            )
            assert (
                response.status_code == 200
                and hashlib.sha256(response.content).hexdigest()
                == row["result"]["outputs"]["video"]["sha256"]
            )
            assert ".mp4" in response.headers["content-disposition"]
            evidence = os.environ.get("MIDEAGENT_PROOF_DIR")
            if evidence and row["node_id"] == "encode_0":
                from pathlib import Path

                root = (
                    Path(evidence)
                    / ("long321" if long_media else "short")
                    / "native-input"
                )
                root.mkdir(exist_ok=True, parents=True)
                for reference in row["inputs"].values():
                    destination = root / reference["storage_key"]
                    destination.parent.mkdir(exist_ok=True, parents=True)
                    __import__("shutil").copyfile(
                        cpu.store.path(owner, reference), destination
                    )
                with cpu.database.connection() as reader:
                    command = reader.execute(
                        "SELECT request FROM node_runs WHERE id=%s", (row["id"],)
                    ).fetchone()["request"]
                (root.parent / "native-command.json").write_text(json.dumps(command))
            media = cpu.store.path(owner, row["result"]["outputs"]["video"])
            decoded = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(media),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
            assert decoded.returncode == 0
            evidence = os.environ.get("MIDEAGENT_PROOF_DIR")
            if evidence:
                from pathlib import Path

                root = Path(evidence) / ("long321" if long_media else "short")
                root.mkdir(exist_ok=True, parents=True)
                (root / (row["node_id"] + ".mp4")).write_bytes(response.content)

    assert (
        len(
            [
                r
                for r in done["runs"]
                if r["node_type"] == "validate_video" and r["status"] == "completed"
            ]
        )
        == 6
    )
    evidence = os.environ.get("MIDEAGENT_PROOF_DIR")
    if evidence:
        from pathlib import Path

        (
            Path(evidence) / ("long321" if long_media else "short") / "result.json"
        ).write_text(
            json.dumps(
                {
                    "duration": 321 if long_media else 0.6,
                    "video_outputs": [
                        {
                            "node": r["node_id"],
                            "reference": r["result"]["outputs"]["video"],
                        }
                        for r in outputs
                    ],
                    "actual_model_calls": calls,
                    "no_models_during_video_continuation": calls == prior,
                    "decode_all_outputs": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def test_language_track_selector_is_a_typed_existing_manifest_control():
    from video_service.node_contracts import node_spec, validate_node

    spec = node_spec("subtitle_track", {"track": "translated.pt-BR"})
    assert spec is not None, "reviewed language selector missing"
    assert spec["inputs"] == {"manifest": "artifact_manifest"} and spec["outputs"] == {
        "subtitles": "subtitle"
    }
    validate_node(
        {
            "node": "subtitle_track",
            "inputs": spec["inputs"],
            "options": {"track": "translated.pt-BR"},
        }
    )


def test_video_selector_rejects_unconfirmed_and_foreign_source_manifest(video_gate):
    runtime, owner, identity, review, calls = video_gate
    service = SubtitleTracks(runtime)
    job = runtime.get(owner, identity)
    before = list(calls)
    manifest = {
        "version": 1,
        "kind": "subtitle_outputs_v1",
        "source_video_sha256": job["snapshot"]["asset"]["sha256"],
        "source_bundle": review["contract"]["source"],
        "review": {},
        "tracks": {},
    }
    reference = runtime.store.put(
        owner, [json.dumps(manifest).encode()], "artifact_manifest"
    )
    with pytest.raises(ValueError, match="confirmed_review"):
        service.select_for_video(job, {"options": {"track": "original"}}, reference)
    manifest["source_video_sha256"] = "0" * 64
    reference = runtime.store.put(
        owner, [json.dumps(manifest).encode()], "artifact_manifest"
    )
    with pytest.raises(ValueError, match="source_mismatch"):
        service.select_for_video(job, {"options": {"track": "original"}}, reference)
    assert calls == before


def test_cancel_during_video_subtitle_staging_adopts_no_new_video_work(
    video_gate, monkeypatch
):
    runtime, owner, identity, review, calls = video_gate
    before = list(calls)
    saved = runtime.review_save(
        owner, review["id"], review["revision"], {**review["draft"], "approved": True}
    )
    runtime.review_confirm(owner, review["id"], saved["revision"])
    admit(runtime, owner, identity)
    runtime.claim_next(
        owner, identity
    )  # committed subtitle files only; selectors stage on next claim
    original = SubtitleTracks.select_for_video
    fired = []

    def cancel_after_read(service, job, node, reference):
        selected = original(service, job, node, reference)
        if not fired:
            fired.append(True)
            runtime.cancel(owner, identity, runtime.get(owner, identity)["revision"])
        return selected

    monkeypatch.setattr(SubtitleTracks, "select_for_video", cancel_after_read)
    assert runtime.claim_next(owner, identity) is None and fired
    state = runtime.get(owner, identity)
    assert not any(
        row["node_type"] in {"encode", "subtitle_track"} for row in state["runs"]
    )

    assert calls == before
