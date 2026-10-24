"""Saved definition/human decision/real PCM -> controlled ASR -> split/trace/translation/subtitles."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
from test_execution import admin as _admin_fixture
from test_execution import admit
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from test_transcription_execution import audio_graph
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime
from video_service.renewal_contracts import validate

admin, db, movie = _admin_fixture, _db_fixture, _movie_fixture


@pytest.fixture
def projection_wire():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            parts = body["contents"][0]["parts"]
            speech = "inlineData" in parts[0]
            if speech:
                response = [
                    {"start": 0.1, "end": 0.4, "text": "Whole sentence", "speaker": "A"}
                ]
            else:
                texts = json.loads(parts[0]["text"])
                assert all(text == "Whole sentence" for text in texts)
                response = ["전체 문장" for _ in texts]
            calls.append("transcription" if speech else "translation")
            data = json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": json.dumps(response)}]},
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
    "split", [True, False, "invalid_clock", "batch", "projection_failure"]
)
def test_formal_projection_is_explicit_and_trace_is_an_actual_cas_output(
    db, admin, movie, tmp_path, projection_wire, split, monkeypatch
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
            name="projection fixture",
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
            name="controlled projection",
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
    )
    runtime.transcription_runtime = TranscriptionRuntime(credentials, **kwargs)
    graph = audio_graph(*refs)
    graph["nodes"][1]["options"] = {
        "processing_profile": "regions_pack_v4",
        "audio_filter": "strong",
        "vad_mode": "off",
    }
    if split:
        graph["nodes"][2]["options"] = {"clock_policy": "packed_projection_v2"}
    if split == "batch":
        graph["nodes"][2]["options"].update(
            batch_policy="bounded_60s_v1", max_model_calls="1"
        )
    if split == "projection_failure":
        from video_service import packed_projection

        def fail_projection(*args):
            raise ValueError("controlled_projection_failure")

        monkeypatch.setattr(packed_projection, "project", fail_projection)
    graph["nodes"].append(
        {
            "id": "review",
            "type": "review",
            "options": {"data_type": "audio", "review_kind": "audio_regions_v1"},
            "position": {"x": 350, "y": 300},
        }
    )
    graph["nodes"].append(
        {
            "id": "subtitle",
            "type": "generate_subtitle",
            "options": {"format": "srt_smi"},
            "position": {"x": 1400, "y": 0},
        }
    )
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
            "id": "projection" + str(i),
            "source": {"node": a, "port": b},
            "target": {"node": c, "port": d},
        }
        for i, (a, b, c, d) in enumerate(links)
    ]
    assert validate(graph)["valid"], validate(graph)
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    asset = runtime.ingest(owner, "synthetic-projection.mp4", movie)
    job = runtime.create(
        owner,
        asset["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    admit(runtime, owner, job["id"])
    waiting = runtime.run_local(owner, job["id"])
    assert waiting["status"] == "review_required" and calls == []
    review = waiting["reviews"][0]
    saved = runtime.review_save(
        owner,
        review["id"],
        review["revision"],
        {
            "approved": True,
            "protected": [],
            "removals": [{"start": 0.2, "end": 0.3, "kind": "breath"}],
        },
    )
    runtime.review_confirm(owner, saved["id"], saved["revision"])
    admit(runtime, owner, job["id"])
    if split == "invalid_clock":
        import hashlib

        from video_service.cpu_agents import canonical

        prepare = runtime.claim_next(owner, job["id"])
        result = runtime.execute_command(owner, prepare)
        reference = result["outputs"]["timeline"]
        path = runtime.store.owner_root(owner) / "attempts" / reference["storage_key"]
        spans = json.loads(path.read_bytes())
        # Deliberately invalid UNPUBLISHED controlled timeline, not real producer proof.
        spans[0]["packed_end"] += 1 / 32000
        raw = canonical(spans)
        path.write_bytes(raw)
        reference.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        runtime.accept(owner, prepare, result)
        asr = runtime.claim_next(owner, job["id"])
        rejected = runtime.execute_command(owner, asr)
        assert rejected["status"] == "failed"
        assert calls == [], (
            "invalid projection clock must be rejected BEFORE paid transport"
        )
        return
    done = runtime.run_local(owner, job["id"])
    if split == "projection_failure":
        assert done["status"] == "failed"
        asr = next(r for r in done["runs"] if r["node_id"] == "asr")
        assert asr["result"]["outputs"] == {}
        held = asr["result"]["transcription"]["projection"]
        assert held["status"] == "held"
        assert (
            json.loads(runtime.store.read(owner, held["packed_transcript"]))[0]["text"]
            == "Whole sentence"
        )
        assert calls == ["transcription"]
        return
    assert done["status"] == "completed", done
    asr = next(r for r in done["runs"] if r["node_id"] == "asr")
    output = json.loads(
        runtime.store.read(owner, asr["result"]["outputs"]["transcript"])
    )
    if split:
        assert [r["start"] for r in output] == pytest.approx([0.1, 0.3])
        assert [r["end"] for r in output] == pytest.approx([0.2, 0.5])
        trace_ref = asr["result"]["outputs"]["trace"]
        trace = json.loads(runtime.store.read(owner, trace_ref))
        assert (
            trace["output_transcript_sha256"]
            == asr["result"]["outputs"]["transcript"]["sha256"]
        )
        assert trace["timeline_sha256"] == asr["inputs"]["timeline"]["sha256"]
        assert trace["rows"][0]["text_policy"] == "repeat-full-sentence-on-each-piece"
        assert (
            json.loads(runtime.store.read(owner, trace["packed_transcript"]))[0]["text"]
            == "Whole sentence"
        )
    else:
        assert [(r["start"], r["end"]) for r in output] == [(0.1, 0.5)]
        assert "trace" not in asr["result"]["outputs"]
    translated = next(r for r in done["runs"] if r["node_id"] == "translate")
    rows = json.loads(
        runtime.store.read(owner, translated["result"]["outputs"]["transcript"])
    )
    assert [r.get("id") for r in rows] == [r.get("id") for r in output]
    subtitle = next(r for r in done["runs"] if r["node_id"] == "subtitle")
    assert (
        "전체 문장"
        in runtime.store.read(
            owner, subtitle["result"]["outputs"]["subtitles"]
        ).decode()
    )
    assert calls == ["transcription", "translation"]
