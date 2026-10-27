"""Explicit fresh PG/AMQPS/scoped TLS S3/installed role/credential bridge journey.
Never accesses operating DB, queues, objects or provider credentials.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import secrets
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
import httpx
import pika
import pytest
from botocore.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from test_execution import admin as _admin_fixture
from test_execution import db as _db_fixture
from test_execution import movie as _movie_fixture
from test_model_role_orchestration import formal
from video_service.cpu_agents import canonical, digest
from video_service.model_role_tool import RoleToolBridge
from video_service.object_store import S3ContentStore
from video_service.postgres.model_roles import ModelRoles

db, admin, movie = _db_fixture, _admin_fixture, _movie_fixture


def test_native_role_mapping_registry_bridge_adoption(db, admin, movie, tmp_path):
    if os.environ.get("RUN_ROLE_NATIVE") != "1":
        pytest.skip("explicit isolated native journey only")
    assert os.environ["MIDEAGENT_TEST_DISPOSABLE"] == "1"
    root = Path("/evidence")
    private = root / "private"
    private.mkdir(exist_ok=True)
    fixture = Path("/fixture/private")
    keys = json.loads((fixture / "operator.json").read_text())
    ca = str(fixture / "ca.pem")
    s3config = Config(
        signature_version="s3v4",
        retries={"total_max_attempts": 1},
        proxies={},
        s3={"addressing_style": "path"},
    )
    s3 = boto3.client(
        "s3",
        endpoint_url="https://model-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=keys["object_user"],
        aws_secret_access_key=keys["object_password"],
        verify=ca,
        config=s3config,
    )
    bucket = "model-role-boundary"
    (tmp_path / "inputs").mkdir()
    (tmp_path / "results").mkdir()
    store = S3ContentStore(s3, bucket, tmp_path / "inputs", prefix="inputs")
    results = S3ContentStore(s3, bucket, tmp_path / "results", prefix="transcription")
    runtime, owner, command = formal(db, admin, movie, tmp_path, store)
    roles = ModelRoles(runtime, result_store=results)
    envelope = roles.enroll(owner, command)
    pin = command["transcription"]["candidates"][0]
    key = runtime.transcription_runtime.credentials.resolve(
        owner, pin["connection_id"], pin["credential_ref"]
    )
    provider_calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert hmac.compare_digest(self.headers.get("x-goog-api-key", ""), key)
            with db.connection() as c:
                call = c.execute(
                    "SELECT status FROM model_role_tool_calls WHERE task_id=%s",
                    (envelope["task"]["task_id"],),
                ).fetchone()
                assert call["status"] == "started"
            assert "/models/" + pin["remote_model"] + ":generateContent" in self.path
            audio = base64.b64decode(
                value["contents"][0]["parts"][0]["inlineData"]["data"]
            )
            provider_calls.append(
                {
                    "audio_sha256": hashlib.sha256(audio).hexdigest(),
                    "model_id": pin["model_id"],
                    "revision": pin["revision"],
                    "connection_revision": pin["connection_revision"],
                    "intent_committed": True,
                    "credential_pin_match": True,
                }
            )
            response = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        [
                                            {
                                                "start": 0.1,
                                                "end": 0.4,
                                                "text": "Native independent role",
                                            }
                                        ]
                                    )
                                }
                            ]
                        },
                    }
                ]
            }
            body = canonical(response)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    provider = ThreadingHTTPServer(("127.0.0.1", 9419), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    runtime.transcription_runtime.transport_factory = lambda: httpx.HTTPTransport(
        retries=0
    )
    bridge = RoleToolBridge(roles, chunk_concurrency=2)
    token = secrets.token_urlsafe(32)

    class Tool(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/speech" or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(403)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 3 * 1024 * 1024:
                self.send_error(413)
                return
            try:
                reply = bridge.invoke(json.loads(self.rfile.read(size)))
            except Exception:
                self.send_error(409, "scoped_call_held")
                return
            body = canonical(reply)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    tls_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "model-role-map-tool")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("model-role-map-tool")]),
            critical=False,
        )
        .sign(tls_key, hashes.SHA256())
    )
    (private / "tool-ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (private / "tool.key").write_bytes(
        tls_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    tool = ThreadingHTTPServer(("0.0.0.0", 8444), Tool)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(private / "tool-ca.pem", private / "tool.key")
    tool.socket = context.wrap_socket(tool.socket, server_side=True)
    threading.Thread(target=tool.serve_forever, daemon=True).start()
    namespace = "mapping_" + secrets.token_hex(6)
    prefix = namespace + ".transcription"
    admin_url = (
        "amqps://"
        + urllib.parse.quote(keys["broker_user"], safe="")
        + ":"
        + urllib.parse.quote(keys["broker_password"], safe="")
        + "@model-mq:5671/model-roles"
    )
    params = pika.URLParameters(admin_url)
    params.ssl_options = pika.SSLOptions(
        ssl.create_default_context(cafile=ca), "model-mq"
    )
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.confirm_delivery()
    for suffix in ["commands", "results"]:
        ch.exchange_declare(
            exchange=prefix + "." + suffix + ".v1", exchange_type="direct", durable=True
        )
    for suffix, exchange, routing in [
        ("inbox", "commands", "transcription"),
        ("cancel", "commands", "cancel"),
        ("result_inbox", "results", "result"),
    ]:
        queue = prefix + "." + suffix + ".v1"
        ch.queue_declare(queue=queue, durable=True)
        ch.queue_bind(
            queue=queue, exchange=prefix + "." + exchange + ".v1", routing_key=routing
        )
    worker_user = "mapworker_" + secrets.token_hex(6)
    worker_password = secrets.token_urlsafe(32)
    # Fresh fixture principal only; the data plane below is verified AMQPS.
    with httpx.Client(
        base_url="http://model-mq:15672",
        auth=(keys["broker_user"], keys["broker_password"]),
        trust_env=False,
    ) as management:
        assert management.put(
            "/api/users/" + worker_user, json={"password": worker_password, "tags": ""}
        ).status_code in {201, 204}
        regex = prefix.replace(".", r"\.")
        permissions = {
            "configure": "^" + regex + r"\.(inbox|cancel)\.v1$",
            "write": "^" + regex + r"\.results\.v1$",
            "read": "^" + regex + r"\.(inbox|cancel)\.v1$",
        }
        assert management.put(
            "/api/permissions/model-roles/" + worker_user, json=permissions
        ).status_code in {201, 204}
    source_key = store._key(owner, envelope["source"]["reference"]["storage_key"])
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": ["arn:aws:s3:::" + bucket + "/" + source_key],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": [
                    "arn:aws:s3:::" + bucket + "/transcription/" + owner + "/*"
                ],
            },
        ],
    }
    sts = boto3.client(
        "sts",
        endpoint_url="https://model-objects:9000",
        region_name="us-east-1",
        aws_access_key_id=keys["object_user"],
        aws_secret_access_key=keys["object_password"],
        verify=ca,
        config=s3config,
    )
    creds = sts.assume_role(
        RoleArn="arn:aws:iam::000000000000:role/model-map",
        RoleSessionName="scoped-role-map",
        DurationSeconds=3600,
        Policy=json.dumps(policy),
    )["Credentials"]
    worker_url = (
        "amqps://"
        + urllib.parse.quote(worker_user, safe="")
        + ":"
        + urllib.parse.quote(worker_password, safe="")
        + "@model-mq:5671/model-roles"
    )
    worker_env = {
        "MAP_ROLE_MQ": worker_url,
        "MAP_S3_ACCESS": creds["AccessKeyId"],
        "MAP_S3_SECRET": creds["SecretAccessKey"],
        "MAP_S3_SESSION": creds["SessionToken"],
        "MAP_TOOL_TOKEN": token,
    }
    (private / "worker.env").write_text(
        "".join(k + "=" + v + chr(10) for k, v in worker_env.items())
    )
    config = {
        "role": "transcription",
        "task_slots": 1,
        "chunk_concurrency": 2,
        "state_root": "/state/runtime",
        "tool_mode": "controlled_registry_scoped_tls",
        "tool_contract": "registry_scoped_v1",
        "tool_url": "https://model-role-map-tool:8444/speech",
        "credential_env": "MAP_TOOL_TOKEN",
        "ca_file": "/run/tool-ca.pem",
        "timeout_seconds": 15,
        "broker": {
            "namespace": namespace,
            "url_env": "MAP_ROLE_MQ",
            "ca_file": "/run/mq-ca.pem",
        },
    }
    for mode, prefixvalue in [("input", "inputs"), ("output", "transcription")]:
        config[mode + "_store"] = {
            "endpoint": "https://model-objects:9000",
            "bucket": bucket,
            "region": "us-east-1",
            "prefix": prefixvalue,
            "cache_root": "/state/" + mode,
            "access_key_env": "MAP_S3_ACCESS",
            "secret_key_env": "MAP_S3_SECRET",
            "session_token_env": "MAP_S3_SESSION",
            "ca_file": "/run/mq-ca.pem",
        }
    (private / "worker.json").write_text(json.dumps(config))

    def send(packet):
        ch.basic_publish(
            exchange=prefix + ".commands.v1",
            routing_key="transcription",
            body=canonical(packet),
            mandatory=True,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                type="mideagent.model.command.v1",
                message_id=packet["task"]["task_id"],
            ),
        )
        return True

    assert roles.publish_exact(owner, command["run_id"], command["attempt_id"], send)
    (root / "ready.json").write_text(
        json.dumps(
            {"namespace": namespace, "task_id": command["attempt_id"], "ready": True}
        )
    )
    try:
        deadline = time.monotonic() + 150
        message = None
        while time.monotonic() < deadline:
            method, props, body = ch.basic_get(
                queue=prefix + ".result_inbox.v1", auto_ack=False
            )
            if method:
                message = json.loads(body)
                break
            conn.process_data_events(time_limit=0.1)
        assert message is not None, "installed independent role result did not arrive"
        assert message["status"] == "completed", message
        before = provider_calls.copy()
        state = roles.receive(message)
        asr = next(r for r in state["runs"] if r["id"] == command["attempt_id"])
        assert asr["status"] == "completed"
        downstream = roles.dispatch_next(owner, command["run_id"])
        assert downstream["agent"]["id"] == "translate"
        assert (
            downstream["inputs"]["transcript"] == asr["result"]["outputs"]["transcript"]
        )
        assert (
            roles.receive(message)["id"] == command["run_id"]
            and provider_calls == before
        )
        ch.basic_ack(method.delivery_tag)
        assert not roles.publish_exact(
            owner, command["run_id"], command["attempt_id"], send
        )
        with db.connection() as c:
            mapping = c.execute(
                "SELECT task_id,request_sha256,envelope_sha256,generation,phase,used_calls FROM model_role_tasks"
            ).fetchone()
            deliveries = c.execute(
                "SELECT count(*) n FROM agent_deliveries WHERE node_run_id=%s",
                (command["attempt_id"],),
            ).fetchone()["n"]
        report = {
            "job_id": command["run_id"],
            "attempt_id": command["attempt_id"],
            "mapping": mapping,
            "native_tls_mq": True,
            "native_tls_s3": True,
            "independent_installed_role": True,
            "registry_frozen_credential_bridge_tls": True,
            "provider_mode": "controlled_loopback_not_quality",
            "provider_calls": provider_calls,
            "central_model_execution_deliveries": deliveries,
            "next_agent": downstream["agent"]["id"],
            "next_input_matches": True,
            "role_result": message,
            "accepted_outputs": asr["result"]["outputs"],
            "envelope_sha256": digest(envelope),
        }
        text = json.dumps(report, default=str, indent=2)
        assert all(
            secret not in text
            for secret in [
                key,
                token,
                worker_password,
                *keys.values(),
                creds["AccessKeyId"],
                creds["SecretAccessKey"],
                creds["SessionToken"],
            ]
        )
        (root / "native-journey.json").write_text(text)
    finally:
        conn.close()
        tool.shutdown()
        tool.server_close()
        provider.shutdown()
        provider.server_close()
