"""Explicit nonpaid TLS endpoint is separate from existing provider address policy."""

import json

import pytest
from video_service.registered_transport import RegisteredPolicy


def test_nonpaid_tls_policy_is_explicit_and_does_not_relax_external_policy(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "mode": "nonpaid_tls",
                "origins": [
                    {
                        "origin": "https://connection-check.internal:9443",
                        "addresses": ["172.28.0.9"],
                    }
                ],
                "ca_file": "/fixture/private/ca.pem",
            }
        )
    )
    with pytest.raises(ValueError):
        RegisteredPolicy.from_file(path)
    policy = RegisteredPolicy.from_file(path, allow_nonpaid=True)
    assert policy.mode == "nonpaid_tls"
    assert policy.approved_origins == {"https://connection-check.internal:9443"}
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "mode": "external",
                "origins": [
                    {
                        "origin": "https://connection-check.internal:9443",
                        "addresses": ["172.28.0.9"],
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError):
        RegisteredPolicy.from_file(path)


def test_independent_role_tool_has_an_explicit_deployment_entrypoint():
    import importlib.util

    assert importlib.util.find_spec("app.role_tool") is not None


def test_nonpaid_pins_never_grant_consent_to_other_provider_origins():
    from video_service.postgres.translation import TranslationRuntime

    runtime = TranslationRuntime(
        None,
        transport_factory=lambda: None,
        approved_origins={
            "https://connection-check.internal:9443",
            "https://api.example.com",
        },
        mode="external",
    )
    runtime.nonpaid_origins = frozenset({"https://connection-check.internal:9443"})
    local = {"endpoint": "https://connection-check.internal:9443/v1"}
    external = {"endpoint": "https://api.example.com/v1"}
    assert not runtime.requires_paid([local])
    assert runtime.requires_paid([external])
    assert runtime.requires_paid([local, external])
