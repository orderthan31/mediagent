"""Installed entrypoint + private TLS forwarding fixture, no published ingress.

Run only with the explicitly disposable PG contract in the admission test module.
The TLS fixture passes all routes; the application, not the proxy, closes intake.
"""

import http.client
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from test_maintenance_admission import case18 as case18  # noqa: PLC0414 -- pytest fixture export


def test_installed_server_tls_auth_018_stop_and_restart_remain_closed(case18, tmp_path):
    db, _store, policy, password, _ = case18
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        api_port = listener.getsockname()[1]

    class Forward(BaseHTTPRequestHandler):
        def forward(self):
            payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            connection = http.client.HTTPConnection("127.0.0.1", api_port, timeout=5)
            try:
                connection.request(
                    self.command,
                    self.path,
                    body=payload,
                    headers={
                        k: v
                        for k, v in self.headers.items()
                        if k.lower() != "connection"
                    },
                )
                response = connection.getresponse()
                body = response.read()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {
                        "connection",
                        "transfer-encoding",
                        "content-length",
                    }:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except (ConnectionError, OSError, http.client.HTTPException):
                self.send_error(502)
            finally:
                connection.close()

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = (
            forward
        )

        def log_message(self, *args):
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Forward)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    proxy.socket = tls.wrap_socket(proxy.socket, server_side=True)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    origin = "https://localhost:" + str(proxy.server_address[1])
    dsn_file = tmp_path / "database.dsn"
    dsn_file.write_text(db.dsn)
    bootstrap = tmp_path / "api.json"
    config = {
        "database_dsn_file": str(dsn_file),
        "content_root": str(tmp_path / "must-not-create"),
        "host": "127.0.0.1",
        "port": api_port,
        "allowed_origins": [origin],
        "secure_cookies": True,
        "admission_policy": {
            "mode": policy.mode,
            "agent_id": policy.agent_id,
            "slot_id": policy.slot_id,
            "handover": False,
        },
    }
    bootstrap.write_text(json.dumps(config))
    command = [
        sys.executable,
        "-m",
        "app.server",
        "--bootstrap-file",
        str(bootstrap),
        "--admission-mode",
        "maintenance",
        "--enable-control",
    ]
    environment = {**os.environ, "MIDEAGENT_ADMISSION_MODE": "normal"}
    log = tmp_path / "server-private.log"
    process = None
    exits = []
    client = httpx.Client(
        base_url=origin,
        verify=ssl.create_default_context(cafile=str(cert_path)),
        timeout=3,
        trust_env=False,
    )

    def start():
        nonlocal process
        with log.open("ab") as output:
            process = subprocess.Popen(
                command, stdout=output, stderr=output, env=environment
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert process.poll() is None, "installed entrypoint exited before liveness"
            response = client.get("/healthz")
            if response.status_code == 200:
                assert response.json()["admission_mode"] == "maintenance"
                assert response.json()["handover_enabled"] is False
                return
            time.sleep(0.05)
        raise AssertionError("installed entrypoint did not open guarded listener")

    def stop():
        nonlocal process
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            code = process.wait(timeout=10)
            exits.append(code)
            assert code in (0, -signal.SIGTERM)
        process = None

    try:
        start()
        assert client.post("/api/jobs", json={}).status_code == 503
        login = client.post(
            "/api/auth/login",
            headers={"Origin": origin},
            json={"username": "maintenance-admin", "password": password},
        )
        assert login.status_code == 200 and "Secure" in login.headers["set-cookie"]
        headers = {"Origin": origin, "X-CSRF-Token": login.json()["csrf_token"]}
        assert client.get("/api/admin/agents/encode").status_code == 200
        assert (
            client.post(
                "/api/admin/agents/encode/target-handover/preview",
                json={},
                headers=headers,
            ).status_code
            == 503
        )
        request_id = __import__("uuid").uuid4().hex
        body = {
            "enabled": False,
            "replicas": 0,
            "revision": 0,
            "request_id": request_id,
        }
        first = client.put(
            "/api/admin/agents/encode/configuration", json=body, headers=headers
        )
        assert first.status_code == 200 and first.json()["phase"] == "queued"
        stop()
        start()
        assert (
            client.get("/api/auth/session").json()["user"]["username"]
            == "maintenance-admin"
        )
        assert client.post("/api/jobs", json={}, headers=headers).status_code == 503
        assert (
            client.put(
                "/api/admin/agents/encode/configuration", json=body, headers=headers
            ).json()
            == first.json()
        )
        assert not (tmp_path / "must-not-create").exists()
        with db.connection() as c:
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM remote_control_requests"
                ).fetchone()["n"]
                == 1
            )
            assert (
                c.execute(
                    "SELECT 1 FROM schema_migrations WHERE name LIKE '012_%' OR name LIKE '019_%'"
                ).fetchone()
                is None
            )
        stop()
        config["admission_policy"]["handover"] = True
        bootstrap.write_text(json.dumps(config))
        bad = subprocess.run(
            command, check=False, capture_output=True, env=environment, timeout=10
        )
        assert bad.returncode == 2
        assert b"Admission startup prerequisites failed" in bad.stderr
        assert b"Traceback" not in bad.stderr
        assert client.get("/healthz").status_code == 502
        config["admission_policy"]["handover"] = False
        bootstrap.write_text(json.dumps(config))
        start()
        assert client.post("/api/jobs", json={}, headers=headers).status_code == 503
        assert client.get("/api/auth/session").json()["user"] is not None
    finally:
        stop()
        client.close()
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=5)
