"""Explicit private transport bootstrap files, never application/model settings."""

import json
from pathlib import Path

from .rabbitmq_transport import BrokerConfig, BrokerError, RabbitClient


def document(path):
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw) if len(raw) <= 8192 else None
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ValueError("invalid_private_transport_file") from None


def secret_file(path):
    try:
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError
        raw = Path(path).read_bytes()
        if not 1 <= len(raw) <= 8192:
            raise ValueError
        value = raw.decode().strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError
        return value
    except (OSError, UnicodeError, ValueError):
        raise ValueError("invalid_private_transport_file") from None


def broker_factory(path):
    return _broker_factory(path, BrokerConfig, RabbitClient)


def engine_broker_factory(path):
    from .engine_transport import EngineBrokerConfig, EngineRabbitClient

    return _broker_factory(path, EngineBrokerConfig, EngineRabbitClient)


def registered_broker_factory(path):
    from .registered_broker import RegisteredBrokerConfig, RegisteredRabbitClient

    return _broker_factory(path, RegisteredBrokerConfig, RegisteredRabbitClient)


def _broker_factory(path, config_type, client_type):
    value = document(path)
    if set(value) - {"namespace", "url_file", "ca_file", "allow_loopback"} or not {
        "namespace",
        "url_file",
    } <= set(value):
        raise BrokerError("invalid_broker_config")
    config = config_type(
        namespace=value["namespace"],
        url_env="PRIVATE_BROKER_URL",
        ca_file=value.get("ca_file"),
        allow_loopback=value.get("allow_loopback", False),
    )

    # Resolve on the calling IO thread, not in a shared Pika connection.
    def connect():
        return client_type.connect(
            config, environ={"PRIVATE_BROKER_URL": secret_file(value["url_file"])}
        )

    return connect


def object_config(path):
    value = document(path)
    expected = {
        "endpoint",
        "bucket",
        "region",
        "prefix",
        "cache_root",
        "access_key_file",
        "secret_key_file",
    }
    if not expected <= set(value) or set(value) - expected - {"ca_file"}:
        raise ValueError("invalid_object_config")
    root = Path(value["cache_root"])
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("invalid_object_cache_root")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = {
        k: v
        for k, v in value.items()
        if k not in ("access_key_file", "secret_key_file")
    }
    config.update(
        access_key_env="PRIVATE_OBJECT_USER", secret_key_env="PRIVATE_OBJECT_PASSWORD"
    )
    return config, {
        "PRIVATE_OBJECT_USER": secret_file(value["access_key_file"]),
        "PRIVATE_OBJECT_PASSWORD": secret_file(value["secret_key_file"]),
    }


def object_store(path):
    from .object_store import from_config

    config, environ = object_config(path)
    return from_config(config, environ=environ)


def object_executor(path):
    from .object_agent import ObjectAgentExecutor

    config, environ = object_config(path)
    environ["PRIVATE_OBJECT_CONFIG"] = json.dumps(config)
    return ObjectAgentExecutor("PRIVATE_OBJECT_CONFIG", environ=environ)
