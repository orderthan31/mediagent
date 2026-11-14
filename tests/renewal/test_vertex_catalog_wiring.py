"""Offline production composition regressions; no database or provider access."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import socket
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in ("packages/shared", "tools/models", "apps/api", "apps/orchestrator"):
    sys.path.insert(0, str(ROOT / path))

OWNER, CONNECTION = "a" * 32, "b" * 32
ORIGINS = frozenset({"https://aiplatform.googleapis.com", "https://oauth2.googleapis.com"})


def forbidden(*args, **kwargs):
    pytest.fail("unexpected network, credential, or eager transport access")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def registry(provider="vertex_ai"):
    from video_service.model_endpoints import FRONTIER_CONNECTIONS
    from video_service.vertex_config import vertex_endpoint
    protocol, endpoint = ("vertex_ai", vertex_endpoint("sample-project", "global")) if provider == "vertex_ai" else FRONTIER_CONNECTIONS[provider]
    row = dict(provider=provider, protocol=protocol, endpoint=endpoint,
               vertex_project="sample-project", vertex_location="global",
               credential_ref="fixture", revision=1, sha256="c" * 64)
    database = SimpleNamespace(connection=lambda: nullcontext(object()))
    return SimpleNamespace(database=database, _connection=lambda *a: ({"active": True}, row))


def credentials():
    return SimpleNamespace(resolve=lambda *a: "synthetic-secret", seal_catalog_entry=forbidden)


def catalog_transport():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"publisherModels": [{"name": "publishers/google/models/offline-unknown"}]}))
    transport.policy = SimpleNamespace(approved_origins=ORIGINS)
    return transport


def test_bootstrap_to_api_query_is_lazy_and_request_owned(monkeypatch):
    from mideagent_orchestrator.bootstrap import runtime_components
    from video_service import transport_files, registered_transport
    from video_service.postgres.credentials import CredentialStore
    from video_service.postgres.registry import Registry
    from mideagent_model_tools import vertex_auth
    from app.renewal import create_app, ModelCatalogRequest

    created, requests = [], []
    policy = registered_transport.RegisteredPolicy("external", ORIGINS, (), "fixture-policy", None)
    original = registered_transport.RegisteredPolicy.vertex_catalog_transport
    def make(self):
        transport = original(self)
        created.append(transport)
        return transport
    monkeypatch.setattr(registered_transport.RegisteredPolicy, "vertex_catalog_transport", make)
    monkeypatch.setattr(registered_transport.RegisteredPolicy, "from_file", lambda *a, **kw: policy)
    def send(self, request):
        assert self.vertex_catalog and self.policy is policy
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1beta1/publishers/google/models"
        return httpx.Response(200, json={"publisherModels": []})
    monkeypatch.setattr(registered_transport.PinnedModelTransport, "handle_request", send)
    monkeypatch.setattr(vertex_auth, "acquire_token", forbidden)
    vault = credentials()
    vault.resolve = forbidden
    store, factory = SimpleNamespace(storage_kind="s3"), SimpleNamespace()
    monkeypatch.setattr(transport_files, "object_store", lambda *a: store)
    monkeypatch.setattr(transport_files, "broker_factory", lambda *a: factory)
    monkeypatch.setattr(transport_files, "registered_broker_factory", lambda *a: object())
    monkeypatch.setattr(CredentialStore, "from_file", lambda *a: vault)
    config = {key: "offline-fixture" for key in ("object_config_file", "broker_config_file", "credential_key_file", "registered_model_config_file", "registered_broker_config_file")}
    config["admission_policy"] = {"mode": "normal"}
    database = registry().database
    result = runtime_components(database, config, enable_broker=True, enable_registered=True)
    assert result == (store, vault, factory)
    assert factory.vertex_catalog_transport_factory.__self__ is policy
    for role in ("translation", "transcription", "vocalization"):
        assert getattr(factory, role + "_runtime").policy_sha256 == policy.sha256
    app = create_app(database, allowed_origins=["http://testserver"], secure_cookies=False,
                     content_store=store, local_execution=True, broker_factory=factory,
                     credential_store=vault)
    assert app.state.vertex_catalog_transport_factory == factory.vertex_catalog_transport_factory
    assert created == requests == []
    monkeypatch.setattr(Registry, "_connection", lambda *a: registry()._connection())
    vault.resolve = lambda *a: "synthetic-secret"
    def token(secret, **kwargs):
        assert secret == "synthetic-secret" and kwargs["approved_origins"] == ORIGINS
        return "synthetic-token"
    monkeypatch.setattr(vertex_auth, "acquire_token", token)
    endpoint = next(route.endpoint for route in app.routes if route.path.endswith("/{identity}/model-catalog"))
    for _ in range(2):
        assert endpoint(CONNECTION, ModelCatalogRequest(connection_revision=1), {"user": {"id": OWNER}})["complete"] is True
    assert len(created) == len(requests) == 2
    assert created[0] is not created[1]
    # Existing explicit app-state test override still wins over production wiring.
    app.state.model_catalog_transport = catalog_transport()
    assert endpoint(CONNECTION, ModelCatalogRequest(connection_revision=1), {"user": {"id": OWNER}})["models"][0]["id"] == "offline-unknown"
    assert len(created) == 2


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic", "xai"])
def test_ordinary_catalog_keeps_default_get_transport(monkeypatch, provider):
    from video_service import model_catalog as m
    seen = []
    def make(selected, **kwargs):
        seen.append(selected)
        def send(request):
            assert request.method == "GET"
            return httpx.Response(200, json={"data": [], "models": [], "has_more": False})
        return httpx.MockTransport(send)
    monkeypatch.setattr(m, "CatalogGetTransport", make)
    result = m.ModelCatalog(registry(provider), credentials(), vertex_transport_factory=forbidden).query(OWNER, CONNECTION, 1)
    assert result["complete"] is True and result["models"] == []
    assert seen == [provider]


@pytest.mark.parametrize("factory", [None, lambda: httpx.MockTransport(forbidden)])
def test_missing_factory_or_policy_remains_closed(monkeypatch, factory):
    from video_service.model_catalog import ModelCatalog, CatalogFailure
    from mideagent_model_tools import vertex_auth
    monkeypatch.setattr(vertex_auth, "acquire_token", forbidden)
    with pytest.raises(CatalogFailure, match="model_catalog_origin_denied"):
        ModelCatalog(registry(), credentials(), vertex_transport_factory=factory).query(OWNER, CONNECTION, 1)


def test_explicit_transport_override_precedes_factory(monkeypatch):
    from video_service.model_catalog import ModelCatalog
    from mideagent_model_tools import vertex_auth
    monkeypatch.setattr(vertex_auth, "acquire_token", lambda *a, **kw: "synthetic-token")
    result = ModelCatalog(registry(), credentials(), transport=catalog_transport(), vertex_transport_factory=forbidden).query(OWNER, CONNECTION, 1)
    assert result["models"][0]["id"] == "offline-unknown"


def test_nonpaid_catalog_delegates_only_to_external_base(monkeypatch):
    from video_service.registered_transport import RegisteredPolicy, WithNonpaidPolicy
    base = RegisteredPolicy("external", ORIGINS, (), "base", None)
    internal = RegisteredPolicy("nonpaid_tls", frozenset({"https://internal.invalid"}), (), "internal", None)
    monkeypatch.setattr(RegisteredPolicy, "from_file", lambda *a, **kw: internal)
    combined = WithNonpaidPolicy(base, "offline-fixture")
    transport = combined.vertex_catalog_transport()
    assert transport.policy is base and transport.vertex_catalog is True
    assert transport.policy.approved_origins == ORIGINS
    assert internal.approved_origins <= combined.approved_origins
    with pytest.raises(httpx.TransportError, match="registered_request_denied"):
        transport.handle_request(httpx.Request("POST", "https://internal.invalid/v1"))


def test_api_without_broker_keeps_factory_absent():
    from app.renewal import create_app
    app = create_app(object(), allowed_origins=["http://testserver"], secure_cookies=False)
    assert app.state.vertex_catalog_transport_factory is None
