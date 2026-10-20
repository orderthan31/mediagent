"""Explicit additive bootstrap provisioning. No rotation, service start or job scan."""

import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from uuid import uuid4


def provision(directory, manifests):
    from video_service.engine_protocol import ENGINE_ROLES, validate_runtime
    from video_service.engine_object_agent import EngineObjectExecutor
    from video_service.rabbitmq_transport import BrokerConfig

    root = Path(directory)
    if (
        not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
        or set(manifests) != ENGINE_ROLES
    ):
        raise ValueError(
            "existing_private_bootstrap_and_four_engine_manifests_required"
        )
    for role, config in manifests.items():
        validate_runtime(config["descriptor"])
        if config["descriptor"]["role"] != role:
            raise ValueError("engine_role_mismatch")
        EngineObjectExecutor(None, config)

    def read(name):
        return json.loads((root / name).read_bytes())

    definitions = read("broker/definitions.json")
    users = {value["name"]: value for value in definitions["users"]}
    permissions = {value["user"]: value for value in definitions["permissions"]}
    if (
        len(users) != len(definitions["users"])
        or len(permissions) != len(definitions["permissions"])
        or "controller" not in users
    ):
        raise ValueError("ambiguous_bootstrap_identity")
    namespace = read("api/controller-broker.json")["namespace"]
    engine_namespace = namespace + ".engine"
    BrokerConfig(namespace=engine_namespace, url_env="PRIVATE_BROKER_URL")
    planned = {}

    def put(name, value, *, replace=False):
        raw = (
            value
            if isinstance(value, bytes)
            else (value + "\n").encode()
            if isinstance(value, str)
            else (json.dumps(value, indent=2) + "\n").encode()
        )
        path = root / name
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError("unsafe_bootstrap_path")
            if path.read_bytes() == raw:
                return
            if not replace:
                raise ValueError("existing_runtime_requires_explicit_upgrade")
        planned[name] = raw

    def identity(user, component, role, *, engine=False):
        url_name = user + "-amqp-url"
        if user not in users:
            if (root / component / url_name).exists():
                raise ValueError("untracked_private_credential")
            password = secrets.token_urlsafe(40)
            salt = os.urandom(4)
            users[user] = {
                "name": user,
                "password_hash": base64.b64encode(
                    salt + hashlib.sha256(salt + password.encode()).digest()
                ).decode(),
                "hashing_algorithm": "rabbit_password_hashing_sha256",
                "tags": [],
            }
            put(
                component + "/" + url_name,
                f"amqps://{user}:{password}@broker:5671/%2Fmideagent",
            )
        elif not (root / component / url_name).is_file():
            raise ValueError("private_credential_missing_preserve_existing_hash")
        prefix = engine_namespace if engine else namespace
        version = "v2" if engine else "v1"
        expected = {
            "user": user,
            "vhost": "/mideagent",
            "configure": "^$",
            "write": "^" + re.escape(prefix + ".results." + version) + "$",
            "read": "^" + re.escape(prefix + "." + role + "." + version) + "$",
        }
        if user in permissions and permissions[user] != expected:
            raise ValueError("existing_role_permissions_differ")
        permissions[user] = expected
        put(
            component
            + "/"
            + ("engine-broker.json" if engine else user + "-broker.json"),
            {
                "namespace": prefix,
                "url_file": "/run/bootstrap/" + url_name,
                "ca_file": "/run/bootstrap/ca.crt",
            },
        )
        for filename in ["ca.crt", "objects-user", "objects-password"]:
            put(component + "/" + filename, (root / "api" / filename).read_bytes())
        object_config = read("api/objects.json")
        object_config["cache_root"] = "/tmp/content"
        put(component + "/objects.json", object_config)

    # A pre-upgrade tree may lack this new CPU-only normalizer.
    identity("preprocess_audio", "agent/preprocess_audio", "preprocess_audio")
    for role, config in sorted(manifests.items()):
        component = "agent/engine/" + role
        identity("engine_" + role, component, role, engine=True)
        put(component + "/runtime.json", config)
    controller = dict(permissions["controller"])
    controller["write"] = (
        "^(?:"
        + re.escape(namespace + ".commands.v1")
        + "|"
        + re.escape(engine_namespace + ".commands.v2")
        + ")$"
    )
    controller["read"] = (
        "^(?:"
        + re.escape(namespace + ".result.v1")
        + "|"
        + re.escape(engine_namespace + ".result.v2")
        + ")$"
    )
    permissions["controller"] = controller
    definitions["users"] = list(users.values())
    definitions["permissions"] = list(permissions.values())
    put("broker/definitions.json", definitions, replace=True)
    for component, user in [("api", "controller"), ("operator", "operator")]:
        put(
            component + "/engine-broker.json",
            {
                "namespace": engine_namespace,
                "url_file": "/run/bootstrap/" + user + "-amqp-url",
                "ca_file": "/run/bootstrap/ca.crt",
            },
        )
        config = read(component + "/api.json")
        if (
            config.get("engine_broker_config_file", "/run/bootstrap/engine-broker.json")
            != "/run/bootstrap/engine-broker.json"
        ):
            raise ValueError("existing_engine_transport_path_differs")
        config["engine_broker_config_file"] = "/run/bootstrap/engine-broker.json"
        put(component + "/api.json", config, replace=True)
    # Validate the complete plan first. Publish credentials before references.
    ordered = sorted(
        planned,
        key=lambda name: (
            name in {"broker/definitions.json", "api/api.json", "operator/api.json"},
            name,
        ),
    )
    for name in ordered:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        os.chmod(path.parent, 0o750)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(path.parent, -1, 10001)
        temporary = path.with_name(path.name + ".pending-" + uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(planned[name])
            os.chmod(temporary, 0o640)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                os.chown(temporary, -1, 10001)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return {
        "engine_roles": sorted(manifests),
        "files_written": len(planned),
        "existing_secrets_rotated": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prepare = sub.add_parser("provision")
    prepare.add_argument("--directory", required=True)
    register = sub.add_parser("register")
    register.add_argument("--bootstrap-file", required=True)
    register.add_argument(
        "--role",
        required=True,
        choices=["preprocess_audio", "transcribe", "translate", "faceswap"],
    )
    register.add_argument("--expected-revision", required=True, type=int)
    register.add_argument("--enable-runtime", action="store_true")
    for child in (prepare, register):
        child.add_argument("--manifest-file", required=True)
        child.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        parser.error("Explicit --apply and preserved bootstrap/DB backups required")
    try:
        from video_service.transport_files import document

        manifests = document(args.manifest_file)
        if args.mode == "provision":
            result = provision(Path(args.directory), manifests)
        else:
            from app.server import load_bootstrap
            from video_service.postgres import Database
            from video_service.postgres.engine_runtimes import EngineRuntimes

            _, dsn = load_bootstrap(args.bootstrap_file)
            row = EngineRuntimes(Database(dsn)).register(
                manifests[args.role]["descriptor"],
                revision=args.expected_revision,
                enabled=args.enable_runtime,
            )
            result = {
                key: row[key] for key in ["role", "revision", "sha256", "enabled"]
            }
        print(json.dumps({"status": "ok", **result}))
        return 0
    except Exception:
        print(
            '{"status":"failed","code":"engine_operator_action_failed_preserve_state"}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
