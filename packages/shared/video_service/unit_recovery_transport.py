"""Opt-in existing private bridge caller; never an external provider executor."""
import json
import math
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .postgres import Conflict


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_private_tool_config_field")
        value[key] = item
    return value


class PrivateUnitRecoveryClient:
    """Configuration is explicit and credentials are read only at an approved call.

    No startup request, ADC, environment credential, HTTP proxy, redirect or retry.
    The caller cannot choose a URL, model, input body or provider credential.
    """
    def __init__(self, config_file, role):
        if role not in {"transcription", "translation"}:
            raise ValueError("unsupported_unit_recovery_role")
        try:
            raw = Path(config_file).read_bytes()
            if not 1 <= len(raw) <= 8192:
                raise ValueError()
            config = json.loads(raw, object_pairs_hook=_unique)
            required = {"version", "role", "tool_url", "token_file", "timeout_seconds"}
            if (type(config) is not dict or not required <= set(config)
                    or set(config) - required - {"ca_file", "max_reply_bytes", "allow_controlled_loopback"}
                    or type(config["version"]) is not int or config["version"] != 1
                    or config["role"] != role):
                raise ValueError()
            text = config["tool_url"]
            if type(text) is not str or len(text) > 2048 or re.search(r"[\s\\%]", text):
                raise ValueError()
            url = urlsplit(text)
            controlled = (config.get("allow_controlled_loopback") is True
                and url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})
            route = "/speech" if role == "transcription" else "/translate"
            if ((not controlled and url.scheme != "https") or not url.hostname
                    or url.username is not None or url.password is not None
                    or url.fragment or url.query or url.path != route or url.port == 0
                    or url.hostname.lower().rstrip('.') in {"metadata.google.internal", "metadata", "instance-data"}):
                raise ValueError()
            timeout = config["timeout_seconds"]
            maximum = config.get("max_reply_bytes", 65536)
            if (type(timeout) not in {int, float} or not math.isfinite(timeout)
                    or not 0 < timeout <= 300 or type(maximum) is not int or not 256 <= maximum <= 65536):
                raise ValueError()
            for name in ("token_file", "ca_file"):
                if name in config and (type(config[name]) is not str or not Path(config[name]).is_absolute()):
                    raise ValueError()
            self.config = config
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError("invalid_private_unit_recovery_config") from None

    def __call__(self, attempt_id, context_sha256):
        if (type(attempt_id) is not str or not re.fullmatch("[a-f0-9]{32}", attempt_id)
                or type(context_sha256) is not str or not re.fullmatch("[a-f0-9]{64}", context_sha256)):
            raise ValueError("invalid_unit_retry_identity")
        config = self.config
        try:
            token_raw = Path(config["token_file"]).read_bytes()
            if not 32 <= len(token_raw) <= 8192:
                raise ValueError()
            token = token_raw.decode("ascii").strip()
            if len(token) < 32 or any(not 33 <= ord(c) <= 126 for c in token):
                raise ValueError()
            context = ssl.create_default_context(cafile=config.get("ca_file"))
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                _NoRedirect(), urllib.request.HTTPSHandler(context=context))
            request = urllib.request.Request(config["tool_url"] + "/unit-recovery",
                data=json.dumps({"attempt_id": attempt_id, "context_sha256": context_sha256}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
            maximum = config.get("max_reply_bytes", 65536)
            with client.open(request, timeout=config["timeout_seconds"]) as response:
                raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError()
            result = json.loads(raw, object_pairs_hook=_unique)
            if (type(result) is not dict or set(result) - {"attempt_id", "status", "error_code"}
                    or result.get("attempt_id") != attempt_id
                    or result.get("status") not in {"pending", "sending", "completed", "failed", "unknown"}
                    or "error_code" in result and (type(result["error_code"]) is not str
                        or not re.fullmatch("[a-z_]{1,80}", result["error_code"]))):
                raise ValueError()
            return result
        except Exception:
            # A failed read does not establish that a bridge did not send. The
            # API reconciles the persisted attempt and never blindly calls again.
            raise Conflict("unit_retry_transport_outcome_unknown") from None
