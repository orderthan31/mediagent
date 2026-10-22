"""Manual deployment operations; never imported as a startup task or DB scanner."""

import argparse
import json
import logging
import signal
import threading


def runtime_components(database, config, *, enable_broker=False,
                       enable_registered=False, allow_controlled_models=False):
    if allow_controlled_models and not enable_registered:
        raise ValueError("controlled_models_require_registered_enablement")
    if enable_registered:
        from .admission import AdmissionPolicy
        if (not enable_broker or AdmissionPolicy.parse(config.get('admission_policy')).mode != 'normal'
                or not {'object_config_file', 'broker_config_file', 'credential_key_file',
                        'registered_model_config_file', 'registered_broker_config_file'} <= set(config)):
            raise ValueError("registered_requires_normal_private_broker_objects_credentials_policy")
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
        if "engine_broker_config_file" in config:
            from video_service.transport_files import engine_broker_factory

            factory.engine_factory = engine_broker_factory(
                config["engine_broker_config_file"]
            )
    if enable_registered:
        from video_service.postgres.transcription import TranscriptionRuntime
        from video_service.postgres.translation import TranslationRuntime
        from video_service.registered_transport import RegisteredPolicy
        from video_service.transport_files import registered_broker_factory

        if factory is None or credentials is None:
            raise ValueError('registered_runtime_not_configured')
        policy = RegisteredPolicy.from_file(config['registered_model_config_file'], allow_controlled=allow_controlled_models)
        factory.registered_factory = registered_broker_factory(config['registered_broker_config_file'])
        factory.registered_policy_sha256 = policy.sha256
        for role, runtime_type in (('translation', TranslationRuntime), ('transcription', TranscriptionRuntime)):
            runtime = runtime_type(credentials, transport_factory=policy.transport,
                                   approved_origins=policy.approved_origins, mode=policy.mode)
            runtime.policy_sha256 = policy.sha256
            setattr(factory, role + '_runtime', runtime)
    return store, credentials, factory


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
        ),
    )
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--enable-registered-models", action="store_true")
    parser.add_argument("--allow-controlled-models", action="store_true")
    parser.add_argument("--apply-migrations", action="store_true")
    parser.add_argument("--initialize-empty-bucket", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "migrate" and not args.apply_migrations:
        parser.error("Migrations require --apply-migrations and a verified backup")
    if (
        args.mode in ("declare-topology", "consume-results", "consume-engine-results", "declare-registered-topology", "consume-registered-models")
        and not args.enable_broker
    ):
        parser.error("Broker operations require --enable-broker")
    if args.mode in ('declare-registered-topology', 'consume-registered-models') and not args.enable_registered_models:
        parser.error("Registered operations require --enable-registered-models")
    if args.allow_controlled_models and not args.enable_registered_models:
        parser.error("Controlled models require --enable-registered-models")
    if args.enable_registered_models and args.mode in ('migrate', 'initialize-objects'):
        parser.error("Registered runtime is separate from migration and object initialization")
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
            database, config, enable_broker=args.enable_broker,
            enable_registered=args.enable_registered_models, allow_controlled_models=args.allow_controlled_models,
        )
        if args.mode == "initialize-objects":
            if getattr(store, "storage_kind", None) != "s3":
                raise ValueError("object_store_required")
            # Never delete, list, overwrite, or import existing user data.
            store.client.create_bucket(Bucket=store.bucket)
            store.client.head_bucket(Bucket=store.bucket)
            print('{"status":"ok","bucket_initialized":true}')
            return 0
        engine_factory = getattr(factory, "engine_factory", None)
        selected_factory = factory
        if args.mode in ('declare-registered-topology', 'consume-registered-models'):
            selected_factory = getattr(factory, 'registered_factory', None)
            if selected_factory is None:
                raise ValueError('registered_transport_not_configured')
        if args.mode == "consume-engine-results":
            if engine_factory is None:
                raise ValueError("engine_transport_not_configured")
            selected_factory = engine_factory
        with selected_factory() as client:
            if args.mode in ("declare-topology", "declare-registered-topology"):
                client.declare()
                if args.mode == 'declare-topology' and engine_factory is not None:
                    with engine_factory() as engine_client:
                        engine_client.declare()
                print('{"status":"ok","topology_declared":true}')
                return 0
            from video_service.postgres.execution import Execution
            from video_service.rabbitmq_controller import BrokerController

            runtime = Execution(database, store, engine_runtime_enabled=engine_factory is not None,
                translation_runtime=getattr(factory, 'translation_runtime', None),
                transcription_runtime=getattr(factory, 'transcription_runtime', None))
            if args.mode == 'consume-registered-models':
                from video_service.registered_broker import ROLE, RegisteredReceiver
                role, receive = ROLE, RegisteredReceiver(runtime, factory).receive
            else:
                role, receive = 'result', BrokerController(runtime, factory).receive
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
