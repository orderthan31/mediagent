"""Explicit renewal deployment entrypoint; bootstrap files are not app settings.

No migrations, job scans, workers, broker connections or provider calls at startup.
The existing renewal_server remains a loopback-only isolated test launcher.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from video_service.bootstrap import FIELDS, OPTIONAL_FIELDS



from video_service.bootstrap import load_bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument(
        "--admission-mode", required=True, choices=("normal", "maintenance")
    )
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument(
        "--enable-registered-models",
        action="store_true",
        help="Enable explicitly bound registered-model MQ delivery; never run providers inside the API",
    )
    parser.add_argument(
        "--allow-controlled-models",
        action="store_true",
        help="Disposable tests only: allow an explicitly pinned loopback HTTP policy",
    )
    parser.add_argument(
        "--enable-control",
        action="store_true",
        help="Connect the fixed-host mailbox/recovery API only; never enroll or start targets",
    )
    parser.add_argument("--enable-full-previews", action="store_true")
    parser.add_argument("--enable-nonpaid-models", action="store_true")
    args = parser.parse_args()
    if args.enable_registered_models and not args.enable_broker:
        parser.error("Registered models require --enable-broker")
    if args.allow_controlled_models and not args.enable_registered_models:
        parser.error("Controlled models require --enable-registered-models")
    try:
        config, dsn = load_bootstrap(args.bootstrap_file)
        from app.admission import AdmissionPolicy

        policy = AdmissionPolicy.parse(config.get("admission_policy"))
        if policy.mode != args.admission_mode:
            raise ValueError("admission_requirement_mismatch")
        if policy.mode == "maintenance" and (
            not args.enable_control
            or args.enable_broker
            or args.enable_registered_models
            or args.allow_controlled_models
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
    from mideagent_orchestrator.bootstrap import runtime_components

    store = credentials = broker_factory = None
    if policy.mode == "normal":
        try:
            store, credentials, broker_factory = runtime_components(
                database,
                config,
                enable_broker=args.enable_broker,
                enable_registered=args.enable_registered_models,
                allow_controlled_models=args.allow_controlled_models,
                enable_nonpaid=args.enable_nonpaid_models,
            )
        except Exception:  # noqa: BLE001 -- private bootstrap values must never reach diagnostics
            parser.error(
                "Runtime startup prerequisites failed; server was not opened. Values are never logged."
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
            full_previews_enabled=args.enable_full_previews,
            translation_runtime=getattr(broker_factory, "translation_runtime", None),
            vocalization_runtime=getattr(broker_factory, "vocalization_runtime", None),
            transcription_runtime=getattr(
                broker_factory, "transcription_runtime", None
            ),
        )
    except (ValueError, psycopg.Error):
        parser.error(
            "Admission startup prerequisites failed; server was not opened. Values are never logged."
        )

    @app.get("/healthz", include_in_schema=False)
    def liveness():
        return {
            "status": "ok",
            "check": "liveness",
            "admission_mode": policy.mode,
            "handover_enabled": policy.handover
            if policy.mode == "maintenance"
            else bool(target_handover),
        }

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
