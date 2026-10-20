"""Manual deployment operations; never imported as a startup task or DB scanner."""

import argparse
import json
import logging
import signal
import threading


def runtime_components(database, config, *, enable_broker=False):
    from video_service.content_store import ContentStore
    from video_service.transport_files import broker_factory, object_store

    store = (
        object_store(config["object_config_file"])
        if "object_config_file" in config
        else ContentStore(config["content_root"])
    )
    credentials = None
    if "credential_key_file" in config:
        from video_service.postgres.credentials import CredentialStore

        credentials = CredentialStore.from_file(database, config["credential_key_file"])
    factory = None
    if enable_broker:
        if "broker_config_file" not in config or "object_config_file" not in config:
            raise ValueError("broker_requires_private_broker_and_object_files")
        factory = broker_factory(config["broker_config_file"])
    return store, credentials, factory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "migrate",
            "declare-topology",
            "consume-results",
            "initialize-objects",
        ),
    )
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--apply-migrations", action="store_true")
    parser.add_argument("--initialize-empty-bucket", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "migrate" and not args.apply_migrations:
        parser.error("Migrations require --apply-migrations and a verified backup")
    if args.mode in ("declare-topology", "consume-results") and not args.enable_broker:
        parser.error("Broker operations require --enable-broker")
    if args.mode == "initialize-objects" and not args.initialize_empty_bucket:
        parser.error("Explicit empty bucket initialization required")
    logging.getLogger("pika").disabled = True
    try:
        from video_service.postgres import Database

        from app.server import load_bootstrap

        config, dsn = load_bootstrap(args.bootstrap_file)
        database = Database(dsn)
        if args.mode == "migrate":
            changed = database.migrate()
            print(json.dumps({"status": "ok", "applied": changed}))
            return 0
        store, _, factory = runtime_components(
            database, config, enable_broker=args.enable_broker
        )
        if args.mode == "initialize-objects":
            if getattr(store, "storage_kind", None) != "s3":
                raise ValueError("object_store_required")
            # Never delete, list, overwrite, or import existing user data.
            store.client.create_bucket(Bucket=store.bucket)
            store.client.head_bucket(Bucket=store.bucket)
            print('{"status":"ok","bucket_initialized":true}')
            return 0
        with factory() as client:
            if args.mode == "declare-topology":
                client.declare()
                print('{"status":"ok","topology_declared":true}')
                return 0
            from video_service.postgres.execution import Execution
            from video_service.rabbitmq_controller import BrokerController

            controller = BrokerController(Execution(database, store), factory)
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            client.serve("result", controller.receive, stop)
        return 0
    except Exception:  # noqa: BLE001 -- never emit DSNs, keys or SDK diagnostics
        print(
            '{"status":"failed","error":{"code":"operator_action_failed","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
