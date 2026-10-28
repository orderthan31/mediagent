"""Manual deployment operations; never imported as a startup task or DB scanner."""

import argparse
import json
import logging
import signal
import threading


def runtime_components(
    database,
    config,
    *,
    enable_broker=False,
    enable_registered=False,
    allow_controlled_models=False,
    enable_nonpaid=False,
):
    if enable_nonpaid and (
        not enable_registered or "nonpaid_model_config_file" not in config
    ):
        raise ValueError("nonpaid_requires_explicit_policy_and_registered_runtime")
    if "nonpaid_model_config_file" in config and not enable_nonpaid:
        raise ValueError("nonpaid_enablement_required")
    if allow_controlled_models and not enable_registered:
        raise ValueError("controlled_models_require_registered_enablement")
    if enable_registered:
        from .admission import AdmissionPolicy

        if (
            not enable_broker
            or AdmissionPolicy.parse(config.get("admission_policy")).mode != "normal"
            or not {
                "object_config_file",
                "broker_config_file",
                "credential_key_file",
                "registered_model_config_file",
                "registered_broker_config_file",
            }
            <= set(config)
        ):
            raise ValueError(
                "registered_requires_normal_private_broker_objects_credentials_policy"
            )
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
        from video_service.postgres.vocalization import VocalizationRuntime
        from video_service.registered_transport import RegisteredPolicy
        from video_service.transport_files import registered_broker_factory

        if factory is None or credentials is None:
            raise ValueError("registered_runtime_not_configured")
        policy = RegisteredPolicy.from_file(
            config["registered_model_config_file"],
            allow_controlled=allow_controlled_models,
        )
        if enable_nonpaid:
            from video_service.registered_transport import WithNonpaidPolicy

            policy = WithNonpaidPolicy(policy, config["nonpaid_model_config_file"])
        factory.registered_factory = registered_broker_factory(
            config["registered_broker_config_file"]
        )
        factory.registered_policy_sha256 = policy.sha256
        for role, runtime_type in (
            ("translation", TranslationRuntime),
            ("transcription", TranscriptionRuntime),
            ("vocalization", VocalizationRuntime),
        ):
            runtime = runtime_type(
                credentials,
                transport_factory=policy.transport,
                approved_origins=policy.approved_origins,
                mode=policy.mode,
            )
            if enable_nonpaid:
                runtime.nonpaid_origins = policy.nonpaid.approved_origins
            runtime.policy_sha256 = policy.sha256
            setattr(factory, role + "_runtime", runtime)
    role_keys = {"model_role_broker_config_file", "model_role_result_config_file"}
    if role_keys & set(config):
        if not enable_registered or not role_keys <= set(config):
            raise ValueError("independent_role_requires_bound_registered_transports")
        from video_service.transport_files import model_role_broker_factory

        factory.model_role_factory = model_role_broker_factory(
            config["model_role_broker_config_file"]
        )
        factory.model_role_result_store = object_store(
            config["model_role_result_config_file"]
        )
    factory.model_role_factories = {}
    factory.model_role_result_stores = {}
    if getattr(factory, "model_role_factory", None):
        factory.model_role_factories["transcription"] = factory.model_role_factory
        factory.model_role_result_stores["transcription"] = (
            factory.model_role_result_store
        )
    translation_keys = {
        "translation_role_broker_config_file",
        "translation_role_result_config_file",
    }
    if translation_keys & set(config):
        if not enable_registered or not translation_keys <= set(config):
            raise ValueError("translation_role_requires_bound_transports")
        from video_service.transport_files import model_role_broker_factory

        factory.model_role_factories["translation"] = model_role_broker_factory(
            config["translation_role_broker_config_file"]
        )
        factory.model_role_result_stores["translation"] = object_store(
            config["translation_role_result_config_file"]
        )
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
            "consume-model-role-results",
            "enroll-model-role",
            "model-role-status",
        ),
    )
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument(
        "--model-role",
        choices=["transcription", "translation"],
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

        from app.server import load_bootstrap

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
            from video_service.model_role_coordinator import ModelRoleCoordinator
            from video_service.postgres.execution import Execution

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
            from video_service.postgres.execution import Execution
            from video_service.rabbitmq_controller import BrokerController

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
