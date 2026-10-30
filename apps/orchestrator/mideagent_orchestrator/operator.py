"""Manual deployment operations; never imported as a startup task or DB scanner."""

import argparse
import json
import logging
import signal
import threading


from mideagent_orchestrator.bootstrap import runtime_components


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "migrate",
            "declare-topology",
            "consume-results",
            "consume-engine-results",
            "declare-registered-topology",
            "consume-registered-models",
            "initialize-objects",
            "consume-model-role-results",
            "enroll-model-role",
            "model-role-status",
        ),
    )
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument(
        "--model-role",
        choices=["transcription", "translation", "vocalization"],
        default="transcription",
    )
    parser.add_argument("--owner")
    parser.add_argument("--job")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--request-id")
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--enable-registered-models", action="store_true")
    parser.add_argument("--allow-controlled-models", action="store_true")
    parser.add_argument("--enable-nonpaid-models", action="store_true")
    parser.add_argument("--apply-migrations", action="store_true")
    parser.add_argument("--initialize-empty-bucket", action="store_true")
    args = parser.parse_args(argv)
    role_modes = {
        "consume-model-role-results",
        "enroll-model-role",
        "model-role-status",
    }
    if args.mode in role_modes and (
        not args.enable_broker or not args.enable_registered_models
    ):
        parser.error(
            "Independent roles require the explicitly bound broker and registered model configuration"
        )
    if args.mode in {"enroll-model-role", "model-role-status"} and (
        not args.owner or not args.job
    ):
        parser.error(
            "Exact --owner and --job are required; historical scanning is not supported"
        )
    if args.mode == "enroll-model-role" and (
        args.revision is None or not args.request_id
    ):
        parser.error("Exact --revision and --request-id are required")
    if args.mode == "migrate" and not args.apply_migrations:
        parser.error("Migrations require --apply-migrations and a verified backup")
    if (
        args.mode
        in (
            "declare-topology",
            "consume-results",
            "consume-engine-results",
            "declare-registered-topology",
            "consume-registered-models",
        )
        and not args.enable_broker
    ):
        parser.error("Broker operations require --enable-broker")
    if (
        args.mode in ("declare-registered-topology", "consume-registered-models")
        and not args.enable_registered_models
    ):
        parser.error("Registered operations require --enable-registered-models")
    if args.allow_controlled_models and not args.enable_registered_models:
        parser.error("Controlled models require --enable-registered-models")
    if args.enable_registered_models and args.mode in ("migrate", "initialize-objects"):
        parser.error(
            "Registered runtime is separate from migration and object initialization"
        )
    if args.mode == "initialize-objects" and not args.initialize_empty_bucket:
        parser.error("Explicit empty bucket initialization required")
    logging.getLogger("pika").disabled = True
    try:
        from video_service.postgres import Database

        from video_service.bootstrap import load_bootstrap

        config, dsn = load_bootstrap(args.bootstrap_file)
        database = Database(dsn)
        if args.mode == "migrate":
            changed = database.migrate()
            print(json.dumps({"status": "ok", "applied": changed}))
            return 0
        store, _, factory = runtime_components(
            database,
            config,
            enable_broker=args.enable_broker,
            enable_registered=args.enable_registered_models,
            allow_controlled_models=args.allow_controlled_models,
            enable_nonpaid=args.enable_nonpaid_models,
        )
        if args.mode == "initialize-objects":
            if getattr(store, "storage_kind", None) != "s3":
                raise ValueError("object_store_required")
            # Never delete, list, overwrite, or import existing user data.
            store.client.create_bucket(Bucket=store.bucket)
            store.client.head_bucket(Bucket=store.bucket)
            print('{"status":"ok","bucket_initialized":true}')
            return 0
        if args.mode in role_modes:
            from mideagent_orchestrator.model_roles import ModelRoleCoordinator
            from mideagent_orchestrator.execution import Execution

            role_runtime = Execution(
                database,
                store,
                engine_runtime_enabled=getattr(factory, "engine_factory", None)
                is not None,
                transcription_runtime=factory.transcription_runtime,
                translation_runtime=factory.translation_runtime,
                vocalization_runtime=factory.vocalization_runtime,
            )
            coordinator = ModelRoleCoordinator(role_runtime, factory)
            if args.mode == "enroll-model-role":
                print(
                    json.dumps(
                        coordinator.enroll_job(
                            args.owner, args.job, args.revision, args.request_id
                        )
                    )
                )
            elif args.mode == "model-role-status":
                print(json.dumps(coordinator.inspect(args.owner, args.job)))
            else:
                stop = threading.Event()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    signal.signal(sig, lambda *_: stop.set())
                with coordinator.role_factories[args.model_role]() as client:
                    client.serve("result", coordinator.receive, stop)
            return 0
        engine_factory = getattr(factory, "engine_factory", None)
        selected_factory = factory
        if args.mode in ("declare-registered-topology", "consume-registered-models"):
            selected_factory = getattr(factory, "registered_factory", None)
            if selected_factory is None:
                raise ValueError("registered_transport_not_configured")
        if args.mode == "consume-engine-results":
            if engine_factory is None:
                raise ValueError("engine_transport_not_configured")
            selected_factory = engine_factory
        with selected_factory() as client:
            if args.mode in ("declare-topology", "declare-registered-topology"):
                client.declare()
                if args.mode == "declare-topology" and engine_factory is not None:
                    with engine_factory() as engine_client:
                        engine_client.declare()
                print('{"status":"ok","topology_declared":true}')
                return 0
            from mideagent_orchestrator.execution import Execution
            from mideagent_orchestrator.controller import BrokerController

            runtime = Execution(
                database,
                store,
                engine_runtime_enabled=engine_factory is not None,
                translation_runtime=getattr(factory, "translation_runtime", None),
                transcription_runtime=getattr(factory, "transcription_runtime", None),
                vocalization_runtime=getattr(factory, "vocalization_runtime", None),
            )
            if args.mode == "consume-registered-models":
                from video_service.registered_broker import ROLE, RegisteredReceiver

                role, receive = ROLE, RegisteredReceiver(runtime, factory).receive
            else:
                role, receive = "result", BrokerController(runtime, factory).receive
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            client.serve(role, receive, stop)
        return 0
    except Exception:  # noqa: BLE001 -- never emit DSNs, keys or SDK diagnostics
        print(
            '{"status":"failed","error":{"code":"operator_action_failed","retryable":false}}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
