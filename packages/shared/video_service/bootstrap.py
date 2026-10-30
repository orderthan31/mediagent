"""Strict private bootstrap contract shared by application composition entrypoints."""
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
    "vocal_role_broker_config_file",
    "vocal_role_result_config_file",
    "translation_role_broker_config_file",
    "translation_role_result_config_file",
    "nonpaid_model_config_file",
    "model_role_broker_config_file",
    "model_role_result_config_file",
    "registered_model_config_file",
    "registered_broker_config_file",
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
