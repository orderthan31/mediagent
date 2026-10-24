"""Real >300s CPU frames, multiple bounded model calls and projection/translation/subtitles."""

import base64
import hashlib
import io
import json
import math
import os
import subprocess
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
from test_execution import admin as _admin_fixture
from test_execution import admit
from test_execution import db as _db_fixture
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime
from video_service.renewal_contracts import validate

admin, db = _admin_fixture, _db_fixture


@pytest.fixture
def long_wire():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            parts = body["contents"][0]["parts"]
            if "inlineData" in parts[0]:
                raw = base64.b64decode(parts[0]["inlineData"]["data"])
                with wave.open(io.BytesIO(raw), "rb") as audio:
                    frames = audio.getnframes()
                    duration = frames / 16000
                index = sum(c["stage"] == "asr" for c in calls)
                rows = [
                    {"start": i * 2 + 0.1, "end": i * 2 + 0.4, "text": "whole sentence"}
                    for i in range(min(20, math.floor(duration / 2)))
                ]
                if index == 0:
                    rows[-1].update(start=59.7, end=60.0)
                if index == 1:
                    rows[0].update(start=0.0, end=0.2)
                result = rows
                calls.append(
                    {
                        "stage": "asr",
                        "frames": frames,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            else:
                texts = json.loads(parts[0]["text"])
                result = ["통제 번역" for _ in texts]
                calls.append(
                    {
                        "stage": "translation",
                        "rows": len(texts),
                        "text_bytes": len(parts[0]["text"].encode("utf-8")),
                    }
                )
            data = json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": json.dumps(result)}]},
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize(
    "mode", ["complete", "too_few_calls", "too_few_translation_calls"]
)
def test_long_frozen_budget_to_six_asr_chunks_projection_two_translations_and_subtitles(
    db, admin, tmp_path, long_wire, mode
):
    owner = admin[0]["id"]
    origin, calls = long_wire
    credentials = CredentialStore(db, os.urandom(32))
    refs = []
    for speech in [True, False]:
        cid, mid = uuid4().hex, uuid4().hex
        row = Registry(db).save_connection(
            owner,
            cid,
            revision=0,
            name="long controlled fixture",
            provider="openai_compatible",
            protocol="gemini",
            endpoint=origin + "/v1",
        )
        row = credentials.save(owner, cid, revision=row["revision"], secret=uuid4().hex)
        Registry(db).save_model(
            owner,
            mid,
            revision=0,
            name="long controlled",
            model="gemini-2.5-flash",
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
    graph = audio_graph(*refs)
    graph["nodes"][0]["options"] = {"media_budget": "audio_long_v5"}
    graph["nodes"][1]["options"] = {
        "media_budget": "audio_long_v5",
        "processing_profile": "regions_long_v5",
        "audio_filter": "strong",
        "vad_mode": "off",
    }
    graph["nodes"][2]["options"] = {
        "media_budget": "audio_long_v5",
        "clock_policy": "packed_projection_v5",
        "batch_policy": "bounded_60s_v1",
        "max_model_calls": "8",
    }
    graph["nodes"][3]["options"] = {
        "media_budget": "audio_long_v5",
        "batch_policy": "bounded_100x16k_v1",
        "max_model_calls": "4",
    }
    if mode == "too_few_calls":
        graph["nodes"][2]["options"]["max_model_calls"] = "4"
    if mode == "too_few_translation_calls":
        graph["nodes"][3]["options"]["max_model_calls"] = "1"
    graph["nodes"] += [
        {
            "id": "review",
            "type": "review",
            "options": {"data_type": "audio", "review_kind": "audio_regions_long_v5"},
            "position": {"x": 350, "y": 300},
        },
        {
            "id": "subtitle",
            "type": "generate_subtitle",
            "options": {"media_budget": "audio_long_v5", "format": "srt_smi"},
            "position": {"x": 1400, "y": 0},
        },
    ]
    graph["edges"] = [
        e
        for e in graph["edges"]
        if not (e["target"]["node"] == "prepare" and e["target"]["port"] == "audio")
    ]
    links = [
        ("audio", "audio", "review", "value"),
        ("review", "value", "prepare", "audio"),
        ("review", "regions", "prepare", "regions"),
        ("translate", "transcript", "subtitle", "transcript"),
    ]
    graph["edges"] += [
        {
            "id": "long" + str(i),
            "source": {"node": a, "port": b},
            "target": {"node": c, "port": d},
        }
        for i, (a, b, c, d) in enumerate(links)
    ]
    assert validate(graph)["valid"], validate(graph)
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    movie = tmp_path / "long-synthetic.mp4"
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
            "-threads",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(movie),
        ],
        check=True,
        capture_output=True,
        timeout=45,
    )
    asset = runtime.ingest(owner, "long-synthetic.mp4", movie.read_bytes())
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    assert job["snapshot"]["audio_pipeline_policy"]["id"] == "audio_long_v5"
    admit(runtime, owner, job["id"])
    held = runtime.run_local(owner, job["id"])
    assert held["status"] == "review_required" and calls == [], [
        (r["node_id"], r["status"], r.get("result", {})) for r in held["runs"]
    ]
    review = held["reviews"][0]
    assert review["contract"]["audio"]["source_frames"] > 300 * 16000
    saved = runtime.review_save(
        owner,
        review["id"],
        review["revision"],
        {
            "approved": True,
            "protected": [],
            "removals": [{"start": 59.8, "end": 60.2, "kind": "breath"}],
        },
    )
    runtime.review_confirm(owner, saved["id"], saved["revision"])
    admit(runtime, owner, job["id"])
    done = runtime.run_local(owner, job["id"])
    if mode == "too_few_calls":
        assert done["status"] == "failed"
        assert calls == [], (
            "insufficient frozen cap for actual PCM frames must be refused before model HTTP"
        )
        if os.getenv("LONG_AUDIO_EVIDENCE_DIR"):
            from pathlib import Path

            Path(os.environ["LONG_AUDIO_EVIDENCE_DIR"]).joinpath(
                mode + ".json"
            ).write_text(
                json.dumps(
                    {
                        "mode": mode,
                        "status": done["status"],
                        "asr_calls": sum(c["stage"] == "asr" for c in calls),
                        "translation_calls": sum(
                            c["stage"] == "translation" for c in calls
                        ),
                        "provider_paid_calls": 0,
                    }
                ),
                encoding="utf-8",
            )
        return
    if mode == "too_few_translation_calls":
        assert done["status"] == "failed"
        assert sum(c["stage"] == "asr" for c in calls) == 6
        assert not any(c["stage"] == "translation" for c in calls), (
            "serialized partition minimum must be checked before translation HTTP"
        )
        if os.getenv("LONG_AUDIO_EVIDENCE_DIR"):
            from pathlib import Path

            Path(os.environ["LONG_AUDIO_EVIDENCE_DIR"]).joinpath(
                mode + ".json"
            ).write_text(
                json.dumps(
                    {
                        "mode": mode,
                        "status": done["status"],
                        "asr_calls": sum(c["stage"] == "asr" for c in calls),
                        "translation_calls": sum(
                            c["stage"] == "translation" for c in calls
                        ),
                        "provider_paid_calls": 0,
                    }
                ),
                encoding="utf-8",
            )
        return
    assert done["status"] == "completed", done
    prepared = next(r for r in done["runs"] if r["node_id"] == "prepare")
    assert prepared["request"]["agent"]["revision"] == "5"
    clock = json.loads(
        runtime.store.read(
            owner, prepared["result"]["outputs"]["timeline"], limit=16 * 1024 * 1024
        )
    )
    assert clock["version"] == 5 and clock["source_frames"] - clock[
        "packed_frames"
    ] == round(0.4 * 16000)
    assert clock["packed_frames"] > 300 * 16000
    source_wav = runtime.store.read(
        owner, review["contract"]["source"], limit=1024 * 1024 * 1024
    )
    packed_wav = runtime.store.read(
        owner, prepared["result"]["outputs"]["audio"], limit=1024 * 1024 * 1024
    )
    with wave.open(io.BytesIO(source_wav), "rb") as source_audio:
        source_pcm = source_audio.readframes(source_audio.getnframes())
    with wave.open(io.BytesIO(packed_wav), "rb") as packed_audio:
        packed_pcm = packed_audio.readframes(packed_audio.getnframes())
    expected_pcm = (
        source_pcm[: round(59.8 * 16000) * 2] + source_pcm[round(60.2 * 16000) * 2 :]
    )
    assert hashlib.sha256(packed_pcm).digest() == hashlib.sha256(expected_pcm).digest()
    asr = next(r for r in done["runs"] if r["node_id"] == "asr")
    rows = json.loads(
        runtime.store.read(
            owner, asr["result"]["outputs"]["transcript"], limit=16 * 1024 * 1024
        )
    )
    trace = json.loads(
        runtime.store.read(
            owner, asr["result"]["outputs"]["trace"], limit=16 * 1024 * 1024
        )
    )
    assert trace["policy"] == "packed_projection_v5"
    assert (
        asr["request"]["resource_budget"]["lease_seconds"]
        == asr["request"]["transcription"]["max_runtime_seconds"]
    )
    receipts = asr["result"]["transcription"]["chunks"]
    previous = 0
    for receipt in receipts:
        assert receipt["span_start"] == previous
        previous = receipt["span_end"]
    assert previous == clock["packed_frames"]
    assert [r["input_sha256"] for r in receipts] == [
        c["sha256"] for c in calls if c["stage"] == "asr"
    ]
    assert trace["rows"][19]["pieces"][-1]["end"] == pytest.approx(
        trace["rows"][20]["pieces"][0]["start"]
    )
    assert (
        trace["rows"][19]["packed_segment"]["id"]
        != trace["rows"][20]["packed_segment"]["id"]
    )
    assert any(len(row["pieces"]) == 2 for row in trace["rows"])
    wire_asr = [call for call in calls if call["stage"] == "asr"]
    wire_translation = [call for call in calls if call["stage"] == "translation"]
    assert len(wire_asr) == 6 and len(wire_translation) == 2
    assert sum(call["frames"] for call in wire_asr) == clock["packed_frames"]
    assert all(
        call["frames"] <= 60 * 16000 and call["bytes"] <= 2 * 1024 * 1024
        for call in wire_asr
    )
    assert sum(call["rows"] for call in wire_translation) == len(rows) and all(
        call["rows"] <= 100 and call["text_bytes"] <= 16000 for call in wire_translation
    )
    translated = next(r for r in done["runs"] if r["node_id"] == "translate")
    output = json.loads(
        runtime.store.read(
            owner, translated["result"]["outputs"]["transcript"], limit=16 * 1024 * 1024
        )
    )
    assert [(r["id"], r["start"], r["end"]) for r in rows] == [
        (r["id"], r["start"], r["end"]) for r in output
    ]
    subtitle = next(r for r in done["runs"] if r["node_id"] == "subtitle")
    assert subtitle["request"]["agent"]["revision"] == "5"
    assert all(
        runtime.store.read(owner, ref, limit=16 * 1024 * 1024)
        for ref in subtitle["result"]["outputs"].values()
    )

    for run in done["runs"]:
        if run["request"].get("resource_budget"):
            limits = run["request"]["resource_budget"]
            assert all(
                ref["bytes"] <= limits["inputs"][port]
                for port, ref in run["inputs"].items()
            )
            assert all(
                ref["bytes"] <= limits["outputs"][port]
                for port, ref in run["result"]["outputs"].items()
            )
    evidence = os.getenv("LONG_AUDIO_EVIDENCE_DIR")
    if evidence:
        from pathlib import Path

        report = {
            "scope": "real isolated PG/CAS/CPU; controlled model HTTP only, NOT recognition quality/GPU/MQ/S3/operating",
            "original_reference": job["snapshot"]["inputs"]["video"],
            "source_frames": clock["source_frames"],
            "packed_frames": clock["packed_frames"],
            "source_audio_sha256": clock["source_sha256"],
            "packed_audio_sha256": clock["audio_sha256"],
            "clock_sha256": prepared["result"]["outputs"]["timeline"]["sha256"],
            "transcript_sha256": asr["result"]["outputs"]["transcript"]["sha256"],
            "trace_sha256": asr["result"]["outputs"]["trace"]["sha256"],
            "asr_chunks": receipts,
            "wire_asr": wire_asr,
            "wire_translation": wire_translation,
            "projected_rows": len(rows),
            "translated_rows": len(output),
            "actual_pcm_cut_verified": True,
            "translation_required_calls": translated["result"]["translation"][
                "required_model_calls"
            ],
            "translation_canonical_input_bytes": translated["result"]["translation"][
                "canonical_source_bytes"
            ],
            "serialized_clock_bytes": prepared["result"]["outputs"]["timeline"][
                "bytes"
            ],
            "serialized_trace_bytes": asr["result"]["outputs"]["trace"]["bytes"],
            "source_budget": job["snapshot"]["audio_pipeline_policy"],
            "model_budget": asr["request"]["resource_budget"],
            "subtitle_outputs": subtitle["result"]["outputs"],
            "actual_gpu": 0,
            "provider_paid_calls": 0,
        }
        Path(evidence).joinpath("long-audio-positive.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
