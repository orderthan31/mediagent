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
OPTIONAL_FIELDS = {"credential_key_file", "object_config_file", "broker_config_file"}


def load_bootstrap(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 8192:
            raise ValueError
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or not FIELDS <= set(value)
            or set(value) - FIELDS - OPTIONAL_FIELDS
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
    parser.add_argument("--enable-broker", action="store_true")
    args = parser.parse_args()
    try:
        config, dsn = load_bootstrap(args.bootstrap_file)
    except ValueError:
        parser.error(
            "Invalid or unreadable explicit bootstrap file; values are never logged."
        )
    import uvicorn
    from video_service.postgres import Database

    from app.renewal import create_app

    database = Database(dsn)
    from app.operator import runtime_components

    store, credentials, broker_factory = runtime_components(
        database, config, enable_broker=args.enable_broker
    )
    app = create_app(
        database,
        allowed_origins=tuple(config["allowed_origins"]),
        secure_cookies=config["secure_cookies"],
        content_store=store,
        credential_store=credentials,
        broker_factory=broker_factory,
        local_execution=args.enable_broker,
    )

    @app.get("/healthz", include_in_schema=False)
    def liveness():
        return {"status": "ok", "check": "liveness"}

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
