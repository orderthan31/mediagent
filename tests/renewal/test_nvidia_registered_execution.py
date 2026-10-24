"""Controlled NVIDIA-clock-shaped producer output on PG/local CAS/HTTP.

NOT a GPU producer, actual NVIDIA inference, S3 or end-to-end GPU journey.
The engine producer/pin contract is tested separately. No storage fence bypass.
"""

import hashlib
import json
import os
import wave
from uuid import uuid4

import httpx
import pytest
from test_execution import movie as _movie_fixture
from test_transcription_execution import admin as _admin_fixture
from test_transcription_execution import audio_graph
from test_transcription_execution import audio_wire as _wire_fixture
from test_transcription_execution import db as _db_fixture
from video_service.content_store import ContentStore
from video_service.cpu_agents import canonical
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime

admin, db, audio_wire, movie = (
    _admin_fixture,
    _db_fixture,
    _wire_fixture,
    _movie_fixture,
)


@pytest.mark.parametrize(
    "valid_clock,batch", [(True, False), (True, True), (False, True)]
)
def test_pinned_nvidia_clock_consumer_reaches_registered_asr_and_translation(
    db, admin, audio_wire, movie, tmp_path, valid_clock, batch
):
    owner = admin[0]["id"]
    origin, calls, _, _ = audio_wire
    credentials = CredentialStore(db, os.urandom(32))
    refs = []
    for stage in ["transcription", "translation"]:
        cid, mid = uuid4().hex, uuid4().hex
        row = Registry(db).save_connection(
            owner,
            cid,
            revision=0,
            name="controlled " + stage,
            provider="openai_compatible",
            protocol="gemini",
            endpoint=origin + "/" + stage + "/v1",
        )
        row = credentials.save(
            owner, cid, revision=row["revision"], secret="synthetic-local-fixture-key"
        )  # Public disposable peer fixture, not an operating key.
        speech = stage == "transcription"
        Registry(db).save_model(
            owner,
            mid,
            revision=0,
            name="controlled " + stage,
            model="gemini-3.8-flash",
            connection_id=cid,
            connection_revision=row["current_revision"],
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
    )
    runtime.transcription_runtime = TranscriptionRuntime(credentials, **kwargs)
    graph = audio_graph(refs[0], refs[1])
    if batch:
        graph["nodes"][2]["options"] = {
            "batch_policy": "bounded_60s_v1",
            "max_model_calls": "3",
        }
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    asset = runtime.ingest(owner, "controlled-clock.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    plan = runtime.plan(owner, job["id"])
    assert plan["ready"], plan["reasons"]
    consent = runtime.confirm(owner, job["id"], plan["token"], uuid4().hex)
    runtime.admit(owner, job["id"], consent["id"], uuid4().hex)
    extract = runtime.claim_next(owner, job["id"])
    runtime.accept(owner, extract, runtime.execute_command(owner, extract))
    prepare = runtime.claim_next(owner, job["id"])
    result = runtime.execute_command(owner, prepare)
    assert result["status"] == "completed"
    # Change only this test's unpublished output artifact to a controlled wrapper.
    # Keep CPU file import and CAS hashing real; do NOT label local CAS as S3.
    attempts = runtime.store.owner_root(owner) / "attempts"
    ref = result["outputs"]["timeline"]
    path = attempts / ref["storage_key"]
    spans = json.loads(path.read_bytes())
    audio = result["outputs"]["audio"]
    with wave.open(str(attempts / audio["storage_key"]), "rb") as stream:
        frames = stream.getnframes()
    raw = canonical(
        {
            "version": 2,
            "audio_sha256": audio["sha256"] if valid_clock else "0" * 64,
            "source_sha256": prepare["inputs"]["audio"]["sha256"],
            "spans": spans,
            "engine": {
                "processing_profile": "nvidia_regions_v4",
                "source_frames": frames,
                "duration_seconds": frames / 16000,
            },
        }
    )
    path.write_bytes(raw)
    ref.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    runtime.accept(owner, prepare, result)
    asr = runtime.claim_next(owner, job["id"])
    assert asr is not None
    result = runtime.execute_command(owner, asr)
    if not valid_clock:
        assert result["status"] == "failed"
        runtime.accept(owner, asr, result)
        assert runtime.claim_next(owner, job["id"]) is None
        assert calls == []
        return
    assert result["status"] == "completed", result
    runtime.accept(owner, asr, result)
    translate = runtime.claim_next(owner, job["id"])
    translated = runtime.execute_command(owner, translate)
    assert translated["status"] == "completed", translated
    runtime.accept(owner, translate, translated)
    assert [call["stage"] for call in calls] == ["transcription", "translation"]
    assert runtime.claim_next(owner, job["id"]) is None
    assert runtime.get(owner, job["id"])["status"] == "completed"
