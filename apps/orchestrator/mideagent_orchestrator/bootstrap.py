"""Application composition for workflow transports, credentials and model policies."""
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
        from video_service.admission_policy import AdmissionPolicy

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
                **({"translation_context_version": 1} if role == "translation" else {}),
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
    vocal_keys = {"vocal_role_broker_config_file", "vocal_role_result_config_file"}
    if vocal_keys & set(config):
        if not enable_registered or not vocal_keys <= set(config):
            raise ValueError("vocal_role_requires_bound_transports")
        from video_service.transport_files import model_role_broker_factory

        factory.model_role_factories["vocalization"] = model_role_broker_factory(
            config["vocal_role_broker_config_file"]
        )
        factory.model_role_result_stores["vocalization"] = object_store(
            config["vocal_role_result_config_file"]
        )
    return store, credentials, factory
