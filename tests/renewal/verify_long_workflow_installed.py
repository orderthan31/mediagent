"""Explicit disposable installed full workflow: real PG/TLS MQ/TLS S3 + HTTP peer.

Not supplier quality, operating rollout, or legacy feature-equivalence acceptance.
No application-source PYTHONPATH override; CPU workers are separate containers.
"""

import base64
import hashlib
import hmac
import json
import os
import signal
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
from app.operator import runtime_components
from app.server import load_bootstrap
from video_service.audio_contract import audio_info
from video_service.cpu_agents import canonical
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.rabbitmq_transport import Delivery
from video_service.registered_broker import decode_reference


def until(read, predicate, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        time.sleep(0.1)
    raise AssertionError("isolated installed state did not reach acceptance boundary")


def main():
    assert os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
    assert os.getuid() == 10001 and "PYTHONPATH" not in os.environ
    root = Path("/run/bootstrap")
    output = Path("/evidence")
    private_logs = Path("/private-logs")
    output.mkdir(exist_ok=True)
    private_logs.mkdir(exist_ok=True)
    for actor in ["api", "results", "worker", "seed"]:
        Path("/tmp/long-" + actor + "-content").mkdir(exist_ok=True)
        Path("/tmp/long-" + actor + "-cache").mkdir(exist_ok=True)
    config, dsn = load_bootstrap(root / "seed.json")
    assert "host=registered-db" in dsn and "registered_long_" in dsn
    database = Database(dsn)
    private = json.loads((root / "fixture-secrets.json").read_text())
    actor = Accounts(database).create(
        "long-installed-admin", private["password"], first=True
    )
    owner = actor["id"]
    store, credentials, factory = runtime_components(
        database,
        config,
        enable_broker=True,
        enable_registered=True,
        allow_controlled_models=True,
    )
    runtime = Execution(
        database,
        store,
        translation_runtime=factory.translation_runtime,
        transcription_runtime=factory.transcription_runtime,
    )
    registry = Registry(database)
    cid, mid = uuid4().hex, uuid4().hex
    connection = registry.save_connection(
        owner,
        cid,
        revision=0,
        name="controlled installed Gemini peer",
        provider="openai_compatible",
        protocol="gemini",
        endpoint="http://127.0.0.1:9419/long/v1",
    )
    connection = credentials.save(
        owner, cid, revision=connection["revision"], secret=private["model_key"]
    )
    model = registry.save_model(
        owner,
        mid,
        revision=0,
        name="controlled audio/text",
        model="gemini-3.8-flash",
        connection_id=cid,
        connection_revision=connection["current_revision"],
        model_types=["multimodal", "speech_recognition", "text"],
        input_modalities=["audio", "text"],
        output_modalities=["text"],
        capabilities=["speech_recognition", "structured_output", "text_generation"],
    )
    graph = json.loads(Path("/proof/full-workflow.json").read_text())
    definition_id = graph.pop("id")
    for node in graph["nodes"]:
        if node["type"] in {"transcribe", "translate"}:
            node["model_ref"] = {"model_id": mid, "revision": model["revision"]}
    saved = runtime.save_definition(owner, definition_id, graph)
    audio = Path("/tmp/long-source.wav")
    with wave.open(str(audio), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * (121 * 16000))
    source_file = Path("/tmp/long-source.mov")
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
            str(audio),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(source_file),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    original = runtime.ingest(owner, source_file.name, source_file.read_bytes())
    original_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
    calls, errors = [], []
    processes, logs, exits = {}, {}, {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            try:
                assert hmac.compare_digest(
                    self.headers.get("x-goog-api-key", ""), private["model_key"]
                )
                assert self.path == "/long/v1/models/gemini-3.8-flash:generateContent"
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                part = body["contents"][0]["parts"][0]
                kind = "transcription" if "inlineData" in part else "translation"
                with database.connection() as db:
                    rows = db.execute(
                        "SELECT a.call_id,a.model_id,a.model_revision,a.connection_revision,a.status,c.context FROM model_chunk_attempts a JOIN model_chunk_cache c ON c.owner_id=a.owner_id AND c.context_sha256=a.context_sha256 WHERE a.owner_id=%s AND a.status='started'",
                        (owner,),
                    ).fetchall()
                assert len(rows) == 1
                intent = rows[0]
                assert (
                    intent["model_id"] == mid
                    and intent["model_revision"] == 1
                    and intent["connection_revision"] == 2
                )
                assert intent["context"]["original_sha256"] == original_sha
                assert intent["context"]["role"] == kind
                if kind == "transcription":
                    raw = base64.b64decode(part["inlineData"]["data"])
                    duration = audio_info(raw)["duration_seconds"]
                    assert (
                        hashlib.sha256(raw).hexdigest()
                        == intent["context"]["input_sha256"]
                    )
                    answer = [
                        {
                            "start": 0,
                            "end": duration,
                            "text": "Controlled installed chunk " + str(len(calls)),
                        }
                    ]
                else:
                    values = json.loads(part["text"])
                    assert len(values) <= 100 and len(part["text"].encode()) <= 16000
                    answer = ["Translated " + value for value in values]
                calls.append(
                    {
                        "kind": kind,
                        "intent_committed": True,
                        "key_pin_match": True,
                        "model_revision": intent["model_revision"],
                        "connection_revision": intent["connection_revision"],
                        "original_sha256": original_sha,
                        "input_sha256": intent["context"]["input_sha256"],
                        "span_start": intent["context"]["span_start"],
                        "span_end": intent["context"]["span_end"],
                    }
                )
                data = canonical(
                    {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"parts": [{"text": json.dumps(answer)}]},
                            }
                        ]
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as error:  # noqa: BLE001 -- controlled HTTP boundary records the exception class only
                errors.append(type(error).__name__)
                self.send_error(500)

    provider = ThreadingHTTPServer(("127.0.0.1", 9419), Handler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()

    def start(name, module, *args):
        leaf = (
            "api.json"
            if name == "api"
            else "worker.json"
            if name == "models"
            else "results.json"
        )
        command = [
            sys.executable,
            "-m",
            module,
            *args,
            "--bootstrap-file",
            str(root / leaf),
            "--enable-broker",
            "--enable-registered-models",
            "--allow-controlled-models",
        ]
        logs[name] = (private_logs / (name + ".log")).open("wb")
        processes[name] = subprocess.Popen(
            command, stdout=logs[name], stderr=subprocess.STDOUT, env=dict(os.environ)
        )

    def request(client, method, path, value=None, expected=200):
        response = (
            client.request(method, path, json=value)
            if value is not None
            else client.request(method, path)
        )
        assert response.status_code == expected, (path, response.status_code)
        return response.json()

    report = {
        "scope": "isolated installed application processes + separate CPU containers + real PG/TLS MQ/TLS MinIO; controlled replies, not model quality",
        "complete": False,
        "operating_changed": False,
        "paid_supplier_calls": 0,
    }
    client = None
    try:
        start("results", "app.operator", "consume-results")
        start("api", "app.server", "--admission-mode", "normal")
        client = httpx.Client(
            base_url="http://127.0.0.1:9418",
            headers={"Origin": "http://127.0.0.1:9418"},
            trust_env=False,
            timeout=15,
        )

        def healthy():
            assert processes["api"].poll() is None
            try:
                return client.get("/healthz").status_code == 200
            except httpx.TransportError:
                return False

        until(healthy, bool)
        login = request(
            client,
            "POST",
            "/api/auth/login",
            {"username": actor["username"], "password": private["password"]},
        )
        client.headers["X-CSRF-Token"] = login["csrf_token"]
        selection = {
            "asset_id": original["asset_id"],
            "definition_id": saved["id"],
            "definition_revision": saved["revision"],
            "options": {"source_language": "en", "target_language": "ko"},
        }
        preview = request(client, "POST", "/api/work-entry/preview", selection)
        ticket = request(
            client,
            "POST",
            "/api/work-entry/create",
            {**selection, "token": preview["token"], "request_id": uuid4().hex},
            expected=201,
        )
        path = "/api/renewal/jobs/" + ticket["id"]
        plan = request(client, "GET", path + "/plan")
        assert plan["ready"]
        consent = request(
            client,
            "POST",
            path + "/confirm",
            {"token": plan["token"], "request_id": uuid4().hex},
        )
        request(
            client,
            "POST",
            path + "/admit",
            {"consent_id": consent["id"], "request_id": uuid4().hex},
        )
        # New fixture heads only; the original ticket and ciphertext revisions remain.
        credentials.save(
            owner,
            cid,
            revision=connection["current_revision"],
            secret="fixture-rotated-" + uuid4().hex,
        )
        registry.save_model(
            owner,
            mid,
            revision=1,
            name="new fixture head",
            model="different-fixture-head",
            connection_id=cid,
            connection_revision=3,
            model_types=["multimodal", "speech_recognition", "text"],
            input_modalities=["audio", "text"],
            output_modalities=["text"],
            capabilities=["speech_recognition", "structured_output", "text_generation"],
        )
        request(client, "POST", path + "/run", {})

        def waiting():
            state = request(client, "GET", path)
            assert state["status"] not in {"failed", "cancelled"}
            return (
                state
                if any(row["node_type"] == "transcribe" for row in state["runs"])
                else None
            )

        until(waiting, bool)
        with factory.registered_factory() as broker:
            method, properties, body = until(
                lambda: broker.channel.basic_get(
                    queue=broker.config.queue("registered"), auto_ack=False
                ),
                lambda result: result[0] is not None,
            )
            delivery = Delivery(
                body,
                properties.type,
                properties.message_id,
                properties.correlation_id,
                properties.content_type,
                properties.content_encoding,
            )
            reference = decode_reference(delivery)
            assert reference["job_id"] == ticket["id"] and set(reference) == {
                "version",
                "owner",
                "job_id",
                "attempt_id",
                "request_sha256",
            }
            broker.channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        start("models", "app.operator", "consume-registered-models")

        def finished():
            state = request(client, "GET", path)
            assert state["status"] not in {"failed", "cancelled"}, [
                (row["node_type"], row["status"]) for row in state["runs"]
            ]
            return state if state["status"] == "completed" else None

        done = until(finished, bool, seconds=60)
        assert not errors and [call["kind"] for call in calls] == [
            "transcription"
        ] * 3 + ["translation"]
        transcribed = next(
            row for row in done["runs"] if row["node_type"] == "transcribe"
        )
        translated = next(
            row for row in done["runs"] if row["node_type"] == "translate"
        )

        def artifact(row, port):
            reply = client.get(
                path + "/artifacts/" + row["id"] + "/" + port + "?download=true"
            )
            assert reply.status_code == 200
            reference = row["result"]["outputs"][port]
            assert (
                hashlib.sha256(reply.content).hexdigest() == reference["sha256"]
                and len(reply.content) == reference["bytes"]
            )
            return reply

        source_rows = artifact(transcribed, "transcript").json()
        target_rows = artifact(translated, "transcript").json()
        assert [
            {k: v for k, v in row.items() if k != "text"} for row in source_rows
        ] == [{k: v for k, v in row.items() if k != "text"} for row in target_rows]
        assert target_rows[-1]["end"] == 121
        for row in (
            item for item in done["runs"] if item["node_type"] == "generate_subtitle"
        ):
            assert artifact(row, "subtitles").content
            sami = artifact(row, "sami")
            assert b"<SAMI>" in sami.content and sami.headers[
                "content-disposition"
            ].endswith('.smi"')
        encoded = next(row for row in done["runs"] if row["node_type"] == "encode")
        video = artifact(encoded, "video")
        result_video = Path("/tmp/installed-result.mp4")
        result_video.write_bytes(video.content)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(result_video),
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        manifest = client.get(path + "/manifest?download=true")
        assert (
            manifest.status_code == 200 and manifest.json()["ticket_id"] == ticket["id"]
        )
        with database.connection() as db:
            ledger = db.execute(
                "SELECT status,count(*) AS count FROM model_chunk_attempts WHERE owner_id=%s GROUP BY status",
                (owner,),
            ).fetchall()
            adopted = db.execute(
                "SELECT count(*) AS count FROM message_inbox i JOIN node_runs n ON n.id=i.message_id WHERE n.owner_id=%s",
                (owner,),
            ).fetchone()["count"]
        assert ledger == [{"status": "completed", "count": 4}] and adopted > 0
        report.update(
            complete=True,
            ticket_id=ticket["id"],
            source_sha256=original_sha,
            seconds=121,
            exact_registered_reference=reference,
            provider_calls=calls,
            model_attempt_counts=ledger,
            accepted_inbox_rows=adopted,
            original_translated_subtitle_formats=["srt", "smi"],
            video_sha256=encoded["result"]["outputs"]["video"]["sha256"],
            full_video_decode=True,
            authenticated_downloads_hash_verified=True,
            frozen_old_key_and_model_revisions=True,
            process_pids={name: process.pid for name, process in processes.items()},
        )
    finally:
        if client is not None:
            client.close()
        for name, process in reversed(list(processes.items())):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            exits[name] = process.wait(timeout=30)
            logs[name].close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(5)
        report["process_exit_codes"] = exits
        text = json.dumps(report, ensure_ascii=False, indent=2)
        assert private["password"] not in text and private["model_key"] not in text
        (output / "independent-long-workflow.json").write_text(text)
    print("independent_long_workflow_complete")


if __name__ == "__main__":
    main()
