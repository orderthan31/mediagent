"""Explicit renewal deployment entrypoint; bootstrap files are not app settings.

No migrations, job scans, workers, broker connections or provider calls at startup.
The existing renewal_server remains a loopback-only isolated test launcher.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

FIELDS = {
    "database_dsn_file",
    "content_root",
    "allowed_origins",
    "host",
    "port",
    "secure_cookies",
}
OPTIONAL_FIELDS = {
    "credential_key_file",
    "object_config_file",
    "broker_config_file",
    "engine_broker_config_file",
}


def load_bootstrap(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 8192:
            raise ValueError
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or not FIELDS <= set(value)
            or set(value) - FIELDS - OPTIONAL_FIELDS - {"admission_policy"}
        ):
            raise ValueError
        if value["host"] not in ("127.0.0.1", "0.0.0.0"):
            raise ValueError
        if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
            raise ValueError
        if type(value["secure_cookies"]) is not bool:
            raise ValueError
        origins = value["allowed_origins"]
        if not isinstance(origins, list) or not 1 <= len(origins) <= 8:
            raise ValueError
        for text in origins:
            origin = urlsplit(text)
            if (
                origin.scheme not in ("http", "https")
                or not origin.hostname
                or origin.username
                or origin.password
                or origin.path
                or origin.query
                or origin.fragment
                or origin.port == 0
                or text != f"{origin.scheme}://{origin.netloc}"
            ):
                raise ValueError
        for name in (
            "database_dsn_file",
            "content_root",
            *(key for key in OPTIONAL_FIELDS if key in value),
        ):
            if not isinstance(value[name], str) or not Path(value[name]).is_absolute():
                raise ValueError
        dsn_bytes = Path(value["database_dsn_file"]).read_bytes()
        if not 1 <= len(dsn_bytes) <= 8192:
            raise ValueError
        dsn = dsn_bytes.decode().strip()
        if not dsn:
            raise ValueError
        return value, dsn
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise ValueError("invalid_bootstrap_file") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--admission-mode", required=True, choices=("normal", "maintenance"))
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--enable-control", action="store_true",
                        help="Connect the fixed-host mailbox/recovery API only; never enroll or start targets")
    args = parser.parse_args()
    try:
        config, dsn = load_bootstrap(args.bootstrap_file)
        from app.admission import AdmissionPolicy

        policy = AdmissionPolicy.parse(config.get("admission_policy"))
        if policy.mode != args.admission_mode:
            raise ValueError("admission_requirement_mismatch")
        if policy.mode == "maintenance" and (
            not args.enable_control or args.enable_broker
            or not config["secure_cookies"]
            or any(urlsplit(o).scheme != "https" for o in config["allowed_origins"])
        ):
            raise ValueError("invalid_maintenance_startup")
    except ValueError:
        parser.error(
            "Invalid or unreadable explicit bootstrap file; values are never logged."
        )
    import uvicorn
    from video_service.postgres import Database

    from app.renewal import create_app

    database = Database(dsn)
    from app.operator import runtime_components

    store = credentials = broker_factory = None
    if policy.mode == "normal":
        store, credentials, broker_factory = runtime_components(
            database, config, enable_broker=args.enable_broker
        )
    remote_control = control_recovery = target_handover = None
    if args.enable_control:
        from video_service.postgres.control_recovery import ControlRecovery
        from video_service.postgres.remote_control import RemoteControl

        remote_control = RemoteControl(database)
        if policy.mode == "normal":
            control_recovery = ControlRecovery(remote_control)
        if policy.mode == "normal" or policy.handover:
            from video_service.postgres.target_handover import TargetHandover
            target_handover = TargetHandover(remote_control)
    import psycopg

    try:
        app = create_app(
            database,
            allowed_origins=tuple(config["allowed_origins"]),
            secure_cookies=config["secure_cookies"],
            content_store=store,
            credential_store=credentials,
            broker_factory=broker_factory,
            local_execution=args.enable_broker,
            remote_control=remote_control,
            control_recovery=control_recovery,
            target_handover=target_handover,
            admission_policy=policy,
        )
    except (ValueError, psycopg.Error):
        parser.error("Admission startup prerequisites failed; server was not opened. Values are never logged.")

    @app.get("/healthz", include_in_schema=False)
    def liveness():
        return {"status": "ok", "check": "liveness", "admission_mode": policy.mode,
                "handover_enabled": policy.handover if policy.mode == "maintenance" else bool(target_handover)}

    uvicorn.run(
        app,
        host=config["host"],
        port=config["port"],
        access_log=False,
        proxy_headers=False,
        log_level="warning",
        reload=False,
    )


if __name__ == "__main__":
    main()
