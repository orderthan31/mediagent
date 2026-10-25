"""Real disposable PG/product orchestration plus controlled audio responses. No quality claim."""

import json
import secrets
from uuid import uuid4

import httpx
from test_execution import movie as _movie
from test_foundation import admin as _admin
from video_service.content_store import ContentStore
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry

try:
    from video_service.postgres.vocalization import VocalizationRuntime
except ModuleNotFoundError:
    VocalizationRuntime = None
admin, movie = _admin, _movie
import hashlib
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from video_service.postgres import Database


@pytest.fixture
def db():
    dsn = os.environ.get("MIDEAGENT_TEST_DSN")
    if not dsn or os.environ.get("MIDEAGENT_TEST_DISPOSABLE") != "1":
        pytest.skip("Explicit disposable PG required")
    schema = "original_upload_" + uuid4().hex
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    instance = Database(make_conninfo(dsn, options="-c search_path=" + schema))
    import video_service.postgres as pg

    with instance.connection() as c:
        c.execute(
            "CREATE TABLE schema_migrations(name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted((Path(pg.__file__).parent / "migrations").glob("*.sql")):
            raw = path.read_bytes()
            c.execute(raw.decode())
            c.execute(
                "INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)",
                (path.name, hashlib.sha256(raw).hexdigest()),
            )
    try:
        yield instance
    finally:
        with psycopg.connect(dsn) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def formal_vocal_attempt(
    db, admin, movie, root, filename="ledger-synthetic.mp4", max_calls=3, claim=True
):
    owner = admin[0]["id"]
    registry, credentials = Registry(db), CredentialStore(db, secrets.token_bytes(32))
    cid, mid = uuid4().hex, uuid4().hex
    conn = registry.save_connection(
        owner,
        cid,
        revision=0,
        name="controlled Gemini audio",
        provider="openai_compatible",
        protocol="gemini",
        endpoint="http://127.0.0.1:9111/v1",
    )
    conn = credentials.save(
        owner, cid, revision=conn["revision"], secret=secrets.token_urlsafe(32)
    )
    registry.save_model(
        owner,
        mid,
        revision=0,
        name="controlled timed audio",
        model="gemini-3.8-flash",
        connection_id=cid,
        connection_revision=conn["current_revision"],
        model_types=["decision"],
        input_modalities=["audio", "text"],
        output_modalities=["text"],
        capabilities=["structured_output", "vocalization_classification"],
    )
    transport = lambda: httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(
            AssertionError("No model request in ledger test")
        )
    )
    asr = VocalizationRuntime(
        credentials,
        transport_factory=transport,
        approved_origins={"http://127.0.0.1:9111"},
        mode="controlled_http",
    )
    runtime = Execution(db, ContentStore(root), vocalization_runtime=asr)
    graph = {
        "catalog_version": 1,
        "revision": 0,
        "name": "controlled automatic vocal",
        "inputs": {"video": "video"},
        "nodes": [
            {
                "id": "extract",
                "type": "extract_audio",
                "options": {},
                "position": {"x": 50, "y": 50},
            },
            {
                "id": "voice",
                "type": "vocalize",
                "model_ref": {"model_id": mid, "revision": 1},
                "options": {
                    "strength": "strong",
                    "batch_policy": "bounded_vocalization_v1",
                    "max_model_calls": str(max_calls),
                },
                "position": {"x": 400, "y": 50},
            },
            {
                "id": "pack",
                "type": "preprocess_audio",
                "options": {
                    "audio_filter": "strong",
                    "processing_profile": "regions_pack_v4",
                    "vad_mode": "off",
                },
                "position": {"x": 700, "y": 50},
            },
        ],
        "edges": [
            {
                "id": "e0",
                "source": {"node": "$input", "port": "video"},
                "target": {"node": "extract", "port": "video"},
            },
            {
                "id": "e1",
                "source": {"node": "extract", "port": "audio"},
                "target": {"node": "voice", "port": "audio"},
            },
            {
                "id": "e2",
                "source": {"node": "extract", "port": "audio"},
                "target": {"node": "pack", "port": "audio"},
            },
            {
                "id": "e3",
                "source": {"node": "voice", "port": "regions"},
                "target": {"node": "pack", "port": "regions"},
            },
        ],
    }
    definition = runtime.save_definition(owner, uuid4().hex, graph)
    original = runtime.ingest(owner, filename, movie)
    ticket = runtime.create(
        owner,
        original["asset_id"],
        definition["id"],
        definition["revision"],
        request_id=uuid4().hex,
        options={"source_language": "en", "target_language": "ko"},
    )
    plan = runtime.plan(owner, ticket["id"])
    assert plan["ready"], plan["reasons"]
    consent = runtime.confirm(owner, ticket["id"], plan["token"], uuid4().hex)
    runtime.admit(owner, ticket["id"], consent["id"], uuid4().hex)
    for _ in range(1):
        command = runtime.claim_next(owner, ticket["id"])
        result = runtime.execute_command(owner, command)
        assert result["status"] == "completed"
        runtime.accept(owner, command, result)
    if not claim:
        return runtime, owner, ticket
    command = runtime.claim_next(owner, ticket["id"])
    assert command["agent"]["id"] == "vocalize" and "vocalization" in command
    return runtime, owner, command


def test_formal_product_vocal_intent_is_committed_before_audio_and_cpu_descendant_completes(
    db, admin, movie, tmp_path
):
    assert callable(VocalizationRuntime), "registered vocal runner missing"
    runtime, owner, command = formal_vocal_attempt(db, admin, movie, tmp_path)
    calls = []

    def reply(request):
        with db.connection() as reader:
            row = reader.execute(
                "SELECT status FROM model_chunk_attempts WHERE owner_id=%s", (owner,)
            ).fetchall()
            count = reader.execute(
                "SELECT issued_count FROM model_call_budgets WHERE owner_id=%s",
                (owner,),
            ).fetchone()["issued_count"]
        assert row == [{"status": "started"}] and count == 1
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(reply)
    result = runtime.execute_command(owner, command)
    assert result["status"] == "completed", result
    assert result["vocalization"]["call_count"] == 1 and len(calls) == 1
    assert result["outputs"]["regions"]["type"] == "audio_regions"
    runtime.accept(owner, command, result)
    downstream = runtime.claim_next(owner, command["run_id"])
    assert downstream["agent"]["id"] == "preprocess_audio"
    done = runtime.execute_command(owner, downstream)
    assert done["status"] == "completed", done
    runtime.accept(owner, downstream, done)
    runtime.claim_next(owner, command["run_id"])
    assert runtime.get(owner, command["run_id"])["status"] == "completed"


def counts(runtime, owner):
    with runtime.database.connection() as reader:
        return (
            reader.execute(
                "SELECT status FROM model_chunk_attempts WHERE owner_id=%s ORDER BY call_id",
                (owner,),
            ).fetchall(),
            reader.execute(
                "SELECT status FROM model_chunk_cache WHERE owner_id=%s", (owner,)
            ).fetchall(),
            reader.execute(
                "SELECT issued_count FROM model_call_budgets WHERE owner_id=%s",
                (owner,),
            ).fetchone()["issued_count"],
        )


def test_delivery_unknown_is_held_and_exact_product_redelivery_never_recharges(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_vocal_attempt(db, admin, movie, tmp_path)
    calls = []

    def timeout(request):
        calls.append(True)
        raise httpx.ReadTimeout("controlled unknown delivery")

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(
        timeout
    )
    result = runtime.execute_command(owner, command)
    assert (
        result["status"] == "failed"
        and result["vocalization"]["held"]
        and result["outputs"] == {}
    ), result["vocalization"]
    assert runtime.execute_command(owner, command) == result
    attempts, cache, count = counts(runtime, owner)
    assert (
        attempts == [{"status": "unknown"}]
        and cache == [{"status": "held"}]
        and count == len(calls) == 1
    )


def test_cancel_after_response_starts_no_confirmation_or_descendant(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_vocal_attempt(db, admin, movie, tmp_path)
    calls = []

    def reply(request):
        calls.append(True)
        runtime.cancel(
            owner, command["run_id"], runtime.get(owner, command["run_id"])["revision"]
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"start":0,"end":0.6,"kind":"breath","certain":true}]'
                                }
                            ]
                        },
                    }
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(reply)
    result = runtime.execute_command(owner, command)
    assert (
        result["status"] == "cancelled" and result["outputs"] == {} and len(calls) == 1
    ), result["vocalization"]
    assert runtime.claim_next(owner, command["run_id"]) is None
    attempts, cache, count = counts(runtime, owner)
    assert (
        attempts == [{"status": "cancelled"}]
        and cache == [{"status": "cancelled"}]
        and count == 1
    )


def test_shared_detect_and_confirmation_budget_is_not_reset_per_phase(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_vocal_attempt(
        db, admin, movie, tmp_path, max_calls=1
    )
    calls = []

    def reply(request):
        calls.append(True)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"start":0,"end":0.6,"kind":"breath","certain":true}]'
                                }
                            ]
                        },
                    }
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(reply)
    result = runtime.execute_command(owner, command)
    assert (
        result["status"] == "failed"
        and result["vocalization"]["error"] == "vocalization_call_budget_exhausted"
    )
    assert result["outputs"] == {} and len(calls) == 1
    assert counts(runtime, owner)[2] == 1


def test_completed_exact_delivery_reuses_receipt_without_model_call(
    db, admin, movie, tmp_path
):
    runtime, owner, command = formal_vocal_attempt(db, admin, movie, tmp_path)
    calls = []

    def reply(request):
        calls.append(True)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(reply)
    result = runtime.execute_command(owner, command)
    assert result["status"] == "completed"
    assert runtime.execute_command(owner, command) == result and len(calls) == 1


def test_authenticated_product_api_real_loopback_detect_confirm_cpu_and_download(
    db, admin, movie, tmp_path
):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.renewal import create_app
    from fastapi.testclient import TestClient

    runtime, owner, ticket = formal_vocal_attempt(
        db, admin, movie, tmp_path, claim=False
    )
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with db.connection() as reader:
                assert (
                    reader.execute(
                        "SELECT count(*)AS n FROM model_chunk_attempts WHERE owner_id=%s AND status='started'",
                        (owner,),
                    ).fetchone()["n"]
                    == 1
                )
            calls.append(body)
            answer = (
                [{"start": 0.05, "end": 0.55, "kind": "breath", "certain": True}]
                if len(calls) == 1
                else {"kind": "breath", "safe_to_remove": True, "speech_overlap": False}
            )
            encoded = json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": json.dumps(answer)}]},
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 9111), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime.vocalization_runtime.transport_factory = lambda: httpx.HTTPTransport(
        retries=0, trust_env=False
    )
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        content_store=runtime.store,
        credential_store=runtime.vocalization_runtime.credentials,
        vocalization_runtime=runtime.vocalization_runtime,
        local_execution=True,
    )
    try:
        with TestClient(app) as client:
            assert client.get("/api/jobs").status_code == 401
            login = client.post(
                "/api/auth/login",
                json={"username": admin[0]["username"], "password": admin[1]},
            )
            assert login.status_code == 200
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            response = client.post(
                "/api/renewal/jobs/" + ticket["id"] + "/run", json={}
            )
            assert response.status_code == 200, response.text
            state = response.json()
            assert state["status"] == "completed", state
            assert len(calls) == 2
            voice = next(row for row in state["runs"] if row["node_type"] == "vocalize")
            download = client.get(
                "/api/renewal/jobs/"
                + ticket["id"]
                + "/artifacts/"
                + voice["id"]
                + "/regions?download=true"
            )
            assert (
                download.status_code == 200
                and hashlib.sha256(download.content).hexdigest()
                == voice["result"]["outputs"]["regions"]["sha256"]
            )
            document = download.json()
            assert len(document["removals"]) == 1
            pack = next(
                row for row in state["runs"] if row["node_type"] == "preprocess_audio"
            )
            timeline = json.loads(
                runtime.store.read(owner, pack["result"]["outputs"]["timeline"])
            )
            from video_service.audio_contract import audio_info

            assert isinstance(timeline, list) and timeline
            source_audio = runtime.store.read(owner, voice["inputs"]["audio"])
            packed_audio = runtime.store.read(owner, pack["result"]["outputs"]["audio"])
            assert (
                audio_info(source_audio)["duration_seconds"]
                > audio_info(packed_audio)["duration_seconds"]
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_model_disabled_after_intent_is_rechecked_before_transport(
    db, admin, movie, tmp_path, monkeypatch
):
    from video_service.postgres.model_batches import _Chunk

    runtime, owner, command = formal_vocal_attempt(db, admin, movie, tmp_path)
    calls = []
    original = _Chunk.before_http

    def disable_then_check(chunk):
        original(chunk)
        registry = Registry(db)
        pin = command["vocalization"]["candidates"][0]
        row = registry.model(owner, pin["model_id"])
        registry.availability(
            owner, pin["model_id"], revision=row["state_revision"], active=False
        )

    monkeypatch.setattr(_Chunk, "before_http", disable_then_check)

    def reply(request):
        calls.append(True)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}
                ]
            },
        )

    runtime.vocalization_runtime.transport_factory = lambda: httpx.MockTransport(reply)
    result = runtime.execute_command(owner, command)
    assert calls == [], "disabled frozen model must not enter the HTTP adapter"
    assert result["status"] == "failed"
