"""Create a NEW private installation only. No network, DB, provider or containers.

Never point this at an existing deployment directory. Never print generated keys.
The provider master key is deployment infrastructure, not a provider credential.
"""

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate(directory, origin):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from app.server import FIELDS, load_bootstrap

    # Reuse strict origin validation without connecting to any database.
    group_ready = hasattr(os, "getgid") and (os.getgid() == 10001 or os.geteuid() == 0)
    directory_mode, file_mode = (0o750, 0o640) if group_ready else (0o755, 0o444)
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(directory, 0o700)
    if not origin.startswith(("http://", "https://")):
        raise ValueError("explicit_origin_required")
    for component in (
        "api",
        "operator",
        "broker",
        "objects",
        "postgres",
        "offline-ca",
        "agent",
    ):
        path = directory / component
        path.mkdir(mode=directory_mode)
        os.chmod(path, directory_mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(path, -1, 10001)

    def write(component, name, value):
        raw = (
            value
            if isinstance(value, bytes)
            else (
                (json.dumps(value, indent=2) if isinstance(value, dict) else value)
                + "\n"
            ).encode()
        )
        path = directory / component / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
        os.chmod(path, file_mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(path, -1, 10001)

    ca_directory = directory / "objects" / "CAs"
    ca_directory.mkdir(mode=directory_mode)
    os.chmod(ca_directory, directory_mode)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(ca_directory, -1, 10001)
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "mideagent private installation CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = ca.public_bytes(serialization.Encoding.PEM)
    write(
        "offline-ca",
        "ca.key",
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    write("offline-ca", "ca.crt", pem)
    for component in ("broker", "objects"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        names = [
            x509.DNSName(component),
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
        cert = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, component)])
            )
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        write(component, "public.crt", cert.public_bytes(serialization.Encoding.PEM))
        write(
            component,
            "private.key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
    db_password = secrets.token_urlsafe(32)
    object_user, object_password = secrets.token_hex(16), secrets.token_urlsafe(40)
    write("postgres", "password", db_password)
    write("objects", "objects-user", object_user)
    write("objects", "objects-password", object_password)
    users, permissions = [], []
    namespace = "mideagent"
    roles = (
        "analyze",
        "extract_audio",
        "preprocess_audio",
        "generate_subtitle",
        "encode",
        "validate_video",
    )
    for role in roles:
        path = directory / "agent" / role
        path.mkdir(mode=directory_mode)
        os.chmod(path, directory_mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(path, -1, 10001)
    for role in ("operator", "controller", *roles):
        password = secrets.token_urlsafe(40)
        salt = os.urandom(4)
        users.append(
            {
                "name": role,
                "password_hash": base64.b64encode(
                    salt + hashlib.sha256(salt + password.encode()).digest()
                ).decode(),
                "hashing_algorithm": "rabbit_password_hashing_sha256",
                "tags": [],
            }
        )
        permissions.append(
            {
                "user": role,
                "vhost": "/mideagent",
                "configure": r"^mideagent\..*" if role == "operator" else "^$",
                "write": r"^mideagent\..*"
                if role == "operator"
                else r"^mideagent\."
                + ("commands" if role == "controller" else "results")
                + r"\.v1$",
                "read": r"^mideagent\..*"
                if role == "operator"
                else r"^mideagent\."
                + ("result" if role == "controller" else role)
                + r"\.v1$",
            }
        )
        component = (
            "operator"
            if role == "operator"
            else "api"
            if role == "controller"
            else "agent/" + role
        )
        write(
            component,
            role + "-amqp-url",
            f"amqps://{role}:{password}@broker:5671/%2Fmideagent",
        )
        write(
            component,
            role + "-broker.json",
            {
                "namespace": namespace,
                "url_file": "/run/bootstrap/" + role + "-amqp-url",
                "ca_file": "/run/bootstrap/ca.crt",
            },
        )
    write(
        "broker",
        "definitions.json",
        {
            "vhosts": [{"name": "/mideagent"}],
            "users": users,
            "permissions": permissions,
        },
    )
    write(
        "broker",
        "rabbitmq.conf",
        "listeners.tcp = none\nlisteners.ssl.default = 5671\nssl_options.cacertfile = /run/bootstrap/ca.crt\nssl_options.certfile = /run/bootstrap/public.crt\nssl_options.keyfile = /run/bootstrap/private.key\nssl_options.verify = verify_none\nssl_options.fail_if_no_peer_cert = false\nmanagement.tcp.ip = 127.0.0.1\ndefinitions.import_backend = local_filesystem\ndefinitions.local.path = /run/bootstrap/definitions.json\ndefinitions.skip_if_unchanged = true\nlog.console.level = warning\n",
    )
    master_key = os.urandom(32)
    for component in (
        "api",
        "operator",
        "broker",
        "objects",
        *("agent/" + role for role in roles),
    ):
        write(component, "ca.crt", pem)
    for component in ("api", "operator", *("agent/" + role for role in roles)):
        # Storage service authentication is infrastructure only. Scope per owner by
        # S3ContentStore; provision narrower S3 IAM accounts before multi-tenant rollout.
        write(component, "objects-user", object_user)
        write(component, "objects-password", object_password)
        write(
            component,
            "objects.json",
            {
                "endpoint": "https://objects:9000",
                "bucket": "mideagent",
                "region": "us-east-1",
                "prefix": "renewal",
                "cache_root": "/data/content" if component == "api" else "/tmp/content",
                "access_key_file": "/run/bootstrap/objects-user",
                "secret_key_file": "/run/bootstrap/objects-password",
                "ca_file": "/run/bootstrap/ca.crt",
            },
        )
    for component in ("api", "operator"):
        write(
            component,
            "database-dsn",
            f"host=postgres dbname=mideagent user=mideagent password={db_password}",
        )
        config = {
            "database_dsn_file": "/run/bootstrap/database-dsn",
            "content_root": "/data/content",
            "allowed_origins": [origin],
            "host": "0.0.0.0",
            "port": 8000,
            "secure_cookies": origin.startswith("https://"),
            "object_config_file": "/run/bootstrap/objects.json",
            "broker_config_file": "/run/bootstrap/"
            + ("controller" if component == "api" else "operator")
            + "-broker.json",
        }
        if component == "api":
            config["credential_key_file"] = "/run/bootstrap/credential-master.key"
            write(component, "credential-master.key", master_key)
        write(component, "api.json", config)
    # Validate exact origins using the launcher without exposing generated values.
    probe = {k: v for k, v in config.items() if k in FIELDS}
    probe["database_dsn_file"] = str(directory / "operator" / "database-dsn")
    write("operator", "validation.json", probe)
    load_bootstrap(directory / "operator" / "validation.json")
    (directory / "operator" / "validation.json").unlink()
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args(argv)
    try:
        generate(args.directory, args.origin)
        print('{"status":"ok","created_new_private_bootstrap":true}')
    except Exception:  # noqa: BLE001 -- never echo secrets or paths; never overwrite
        print(
            '{"status":"failed","error":"bootstrap_creation_failed_preserve_partial_directory"}'
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
