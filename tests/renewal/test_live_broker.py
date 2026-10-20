"""Opt-in real TLS RabbitMQ/MinIO and independent CPU/result processes.

Never discover operational endpoints. Only random labeled tmpfs containers, a new
private bootstrap, the explicitly disposable PG fixture and synthetic media.
"""

import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pika
import pytest
from app.bootstrap import generate
from test_execution import admit, setup
from test_execution import movie as _movie
from test_foundation import admin as _admin
from test_foundation import db as _db
from video_service.postgres.execution import Execution
from video_service.rabbitmq_controller import BrokerController
from video_service.rabbitmq_transport import BrokerError, envelope
from video_service.transport_files import broker_factory, object_store

admin, db, movie = _admin, _db, _movie
pytestmark = pytest.mark.skipif(
    os.environ.get("MIDEAGENT_TEST_LIVE_BROKER") != "1",
    reason="explicit disposable live broker opt-in required",
)
BROKER = "rabbitmq:4.2.9-management-alpine@sha256:5606bedb254b7b5bcf890ad8d9237abb59f9bc0ee98d9e9b9f0c113f4f489b6c"


def docker(*args):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=90, check=False
    )
    if result.returncode:
        raise RuntimeError("isolated_docker_command_failed")
    return (
        (result.stdout + result.stderr).strip()
        if args[0] == "logs"
        else result.stdout.strip()
    )


def test_live_tls_persistent_roundtrip_ack_duplicate_and_poison(
    db, admin, movie, tmp_path
):
    assert os.environ.get("MIDEAGENT_TEST_DISPOSABLE") == "1"
    identity = uuid4().hex
    network = "mideagent-test-" + identity
    names = [network + "-broker", network + "-objects"]
    private = generate(tmp_path / "bootstrap", "http://testserver")
    processes = []
    created = []
    docker(
        "network",
        "create",
        "--internal",
        "--label",
        "mideagent.scope=isolated-live-broker",
        network,
    )
    try:
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization

        network_info = json.loads(docker("network", "inspect", network))[0]
        subnet = ipaddress.ip_network(network_info["IPAM"]["Config"][0]["Subnet"])
        hosts = [str(subnet.network_address + 2), str(subnet.network_address + 3)]
        ca = x509.load_pem_x509_certificate(
            (private / "offline-ca" / "ca.crt").read_bytes()
        )
        ca_key = serialization.load_pem_private_key(
            (private / "offline-ca" / "ca.key").read_bytes(), password=None
        )
        for component, host in zip(("broker", "objects"), hosts):
            path = private / component / "public.crt"
            leaf = x509.load_pem_x509_certificate(path.read_bytes())
            certificate = (
                x509.CertificateBuilder()
                .subject_name(leaf.subject)
                .issuer_name(ca.subject)
                .public_key(leaf.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(leaf.not_valid_before_utc)
                .not_valid_after(leaf.not_valid_after_utc)
                .add_extension(
                    x509.SubjectAlternativeName(
                        [
                            x509.DNSName(component),
                            x509.IPAddress(ipaddress.ip_address(host)),
                        ]
                    ),
                    critical=False,
                )
                .sign(ca_key, hashes.SHA256())
            )
            path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        common = [
            "--network",
            network,
            "--label",
            "mideagent.scope=isolated-live-broker",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "128",
            "--cpus",
            "1",
        ]
        docker(
            "run",
            "-d",
            "--name",
            names[0],
            *common,
            "--ip",
            hosts[0],
            "--network-alias",
            "broker",
            "--hostname",
            names[0],
            "--user",
            "100:10001",
            "--memory",
            "768m",
            "--tmpfs",
            "/var/lib/rabbitmq:uid=100,gid=10001,mode=0700,size=128m",
            "-v",
            str(private / "broker") + ":/run/bootstrap:ro",
            "-e",
            "RABBITMQ_CONFIG_FILE=/run/bootstrap/rabbitmq",
            "-e",
            "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2 +A 4",
            BROKER,
        )
        created.append(names[0])
        docker(
            "run",
            "-d",
            "--name",
            names[1],
            *common,
            "--ip",
            hosts[1],
            "--network-alias",
            "objects",
            "--user",
            "10001:10001",
            "--memory",
            "1g",
            "--read-only",
            "--tmpfs",
            "/data:uid=10001,gid=10001,mode=0700,size=128m",
            "--tmpfs",
            "/tmp:uid=10001,gid=10001,mode=0700,size=64m",
            "-v",
            str(private / "objects") + ":/run/bootstrap:ro",
            "mideagent-objects:9e49d5e",
        )
        created.append(names[1])
        for name, host in zip(names, hosts):
            info = json.loads(docker("inspect", name))[0]
            assert info["Config"]["Labels"]["mideagent.scope"] == "isolated-live-broker"
            assert info["NetworkSettings"]["Networks"][network]["IPAddress"] == host
            assert (
                not info["HostConfig"]["PortBindings"] and info["HostConfig"]["Tmpfs"]
            )
            assert all(mount["RW"] is False for mount in info["Mounts"])
        # Transform only this test's NEW files to loopback paths/ports.
        for folder in [
            private / "api",
            private / "operator",
            *(private / "agent" / role for role in ("encode", "validate_video")),
        ]:
            for path in folder.glob("*.json"):
                value = json.loads(path.read_text())
                for key in (
                    "url_file",
                    "ca_file",
                    "access_key_file",
                    "secret_key_file",
                    "database_dsn_file",
                ):
                    if key in value:
                        value[key] = str(folder / Path(value[key]).name)
                if "endpoint" in value:
                    value["endpoint"] = "https://" + hosts[1] + ":9000"
                if "cache_root" in value:
                    value["cache_root"] = str(tmp_path / (folder.name + "-cache"))
                if "object_config_file" in value:
                    value["object_config_file"] = str(folder / "objects.json")
                if "broker_config_file" in value:
                    value["broker_config_file"] = str(
                        folder
                        / (
                            "controller-broker.json"
                            if folder.name == "api"
                            else "operator-broker.json"
                        )
                    )
                value.pop("credential_key_file", None)
                path.write_text(json.dumps(value))
            for path in folder.glob("*-amqp-url"):
                path.write_text(
                    path.read_text().replace("@broker:5671/", "@" + hosts[0] + ":5671/")
                )
        (private / "api" / "database-dsn").write_text(db.dsn)
        factory = broker_factory(private / "operator" / "operator-broker.json")
        deadline = time.monotonic() + 90
        while True:
            try:
                with factory() as client:
                    client.declare()
                break
            except BrokerError:
                if time.monotonic() > deadline:
                    raise RuntimeError("isolated_broker_readiness_timeout") from None
                time.sleep(0.25)
        context = ssl.create_default_context(cafile=str(private / "api" / "ca.crt"))
        while True:
            try:
                with urllib.request.urlopen(
                    "https://" + hosts[1] + ":9000" + "/minio/health/live",
                    context=context,
                    timeout=1,
                ) as response:
                    assert response.status == 200
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("isolated_objects_readiness_timeout") from None
                time.sleep(0.25)
        store = object_store(private / "api" / "objects.json")
        store.client.create_bucket(Bucket=store.bucket)
        store.client.head_bucket(Bucket=store.bucket)
        runtime = Execution(db, store)
        owner = admin[0]["id"]
        _, _, job = setup(runtime, owner, movie)
        admit(runtime, owner, job["id"])
        controller = BrokerController(
            runtime, broker_factory(private / "api" / "controller-broker.json")
        )
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        for role in ("encode", "validate_video"):
            folder = private / "agent" / role
            stream = (tmp_path / (role + ".log")).open("wb")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "mideagent_cpu.broker",
                    "--enable-broker",
                    "--agent",
                    role,
                    "--broker-config-file",
                    str(folder / (role + "-broker.json")),
                    "--object-config-file",
                    str(folder / "objects.json"),
                ],
                env=env,
                stdout=stream,
                stderr=stream,
            )
            processes.append((process, stream))
        stream = (tmp_path / "results.log").open("wb")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.operator",
                "consume-results",
                "--bootstrap-file",
                str(private / "api" / "api.json"),
                "--enable-broker",
            ],
            env=env,
            stdout=stream,
            stderr=stream,
        )
        processes.append((process, stream))
        controller.dispatch(owner, job["id"])
        deadline = time.monotonic() + 60
        while True:
            state = runtime.get(owner, job["id"])
            if state["status"] == "completed":
                break
            assert state["status"] not in ("failed", "blocked", "cancelled"), (
                "synthetic_job_did_not_complete"
            )
            assert all(p.poll() is None for p, _ in processes), (
                "isolated_consumer_exited"
            )
            if time.monotonic() > deadline:
                raise RuntimeError("isolated_job_timeout")
            time.sleep(0.1)
        assert len(state["runs"]) == 2
        for run in state["runs"]:
            for reference in run["result"]["outputs"].values():
                assert (
                    hashlib.sha256(
                        store.path(owner, reference).read_bytes()
                    ).hexdigest()
                    == reference["sha256"]
                )
        with db.connection() as sql:
            row = sql.execute(
                "SELECT request AS command,result FROM node_runs WHERE job_id=%s AND node_id=%s",
                (job["id"], "n1"),
            ).fetchone()
        # Duplicate exact command is served from remote attempt receipt; no new run.
        with factory() as client:
            client.publish(envelope(owner, row["command"]))
            client.channel.basic_publish(
                exchange=client.config.commands,
                routing_key="encode",
                body=b"{}",
                mandatory=True,
                properties=pika.BasicProperties(
                    type="invalid.synthetic",
                    message_id=uuid4().hex,
                    correlation_id=job["id"],
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                ),
            )
            deadline = time.monotonic() + 10
            while True:
                dead = client.channel.queue_declare(
                    queue=client.config.queue("encode") + ".dead", passive=True
                ).method.message_count
                counts = [
                    client.channel.queue_declare(
                        queue=client.config.queue(role), passive=True
                    ).method
                    for role in ("encode", "validate_video", "result")
                ]
                if dead == 1 and all(q.message_count == 0 for q in counts):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("isolated_ack_or_dead_letter_timeout")
                client.connection.process_data_events(time_limit=0.1)
        statistics = json.loads(
            docker(
                "exec",
                "--env",
                "RABBITMQ_CTL_ERL_ARGS=+S 1:1 +A 1",
                names[0],
                "rabbitmqctl",
                "--quiet",
                "--formatter",
                "json",
                "list_queues",
                "-p",
                "/mideagent",
                "name",
                "messages_ready",
                "messages_unacknowledged",
            )
        )
        for queue in statistics:
            assert queue["messages_unacknowledged"] == 0
            expected_ready = 1 if queue["name"] == "mideagent.encode.v1.dead" else 0
            assert queue["messages_ready"] == expected_ready
        with db.connection() as sql:
            assert (
                sql.execute(
                    "SELECT count(*) AS n FROM node_runs WHERE job_id=%s", (job["id"],)
                ).fetchone()["n"]
                == 2
            )
        assert runtime.get(owner, job["id"])["status"] == "completed"
        assert all(p.poll() is None for p, _ in processes)
    finally:
        for process, stream in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            stream.close()
        for name in reversed(created):
            # Exact random identity and label must agree before cleanup.
            info = json.loads(docker("inspect", name))[0]
            assert info["Config"]["Labels"]["mideagent.scope"] == "isolated-live-broker"
            raw = docker("logs", name)
            # Store sanitized startup diagnostics before removing only this fixture.
            import re
            from urllib.parse import urlsplit

            for credential in private.rglob("*"):
                if not credential.is_file():
                    continue
                if credential.name.endswith("-amqp-url"):
                    value = urlsplit(credential.read_text().strip()).password
                    if value:
                        raw = raw.replace(value, "[REDACTED]")
                elif credential.name in (
                    "objects-user",
                    "objects-password",
                    "password",
                ):
                    raw = raw.replace(credential.read_text().strip(), "[REDACTED]")
            raw = re.sub(r"password=[^\s]+", "password=[REDACTED]", raw)
            (tmp_path / (name.rsplit("-", 1)[-1] + "-container.log")).write_text(raw)
            docker("rm", "-f", name)
        docker("network", "rm", network)
