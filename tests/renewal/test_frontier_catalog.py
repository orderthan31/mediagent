"""Named-provider registration and non-generating server catalog boundaries."""

import secrets
from uuid import uuid4

import httpx
import pytest
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_foundation import admin as _admin
from test_foundation import app_client, login
from test_foundation import db as _db
from video_service.model_catalog import CatalogFailure, classify, fetch_catalog
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.registry import Registry

db, admin = _db, _admin


def test_official_openai_catalog_uses_saved_key_server_side_and_does_not_infer_unknown_capabilities(
    db, admin
):
    owner, identity = admin[0]["id"], uuid4().hex
    registry = Registry(db)
    store = CredentialStore(db, secrets.token_bytes(32))
    saved = registry.save_connection(
        owner, identity, revision=0, name="OpenAI", provider="openai"
    )
    key = secrets.token_urlsafe(24)
    saved = store.save(owner, identity, revision=saved["revision"], secret=key)
    calls = []

    def respond(request):
        assert (
            request.method == "GET"
            and str(request.url) == "https://api.openai.com/v1/models"
        )
        assert request.headers["Authorization"] == "Bearer " + key
        assert not request.content
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5.5", "owned_by": "openai"},
                    {"id": "unknown-future-id", "owned_by": "openai"},
                ],
                "object": "list",
            },
        )

    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=store,
    )
    app.state.model_catalog_transport = httpx.MockTransport(respond)
    with TestClient(app) as client:
        login(client, admin)
        response = client.post(
            "/api/settings/serving-connections/" + identity + "/model-catalog",
            json={"connection_revision": saved["current_revision"]},
        )
        assert response.status_code == 200
        assert key not in response.text
        data = response.json()
        assert data["inference_verified"] is False and data["complete"] is True
        assert [item["id"] for item in data["models"]] == [
            "gpt-5.5",
            "unknown-future-id",
        ]
        assert data["models"][0]["runtime_uses"] == ["translation"]
        assert data["models"][0]["registration_token"]
        assert data["models"][1]["profile"] is None
        assert data["models"][1]["runtime_uses"] == []
        assert calls == ["/v1/models"]


def test_whisper_is_the_specific_timed_transcription_contract_not_an_arbitrary_audio_name():
    result = classify("openai", {"id": "whisper-1"}, "openai")
    assert result["runtime_uses"] == ["transcription"]
    assert result["profile"]["capabilities"] == ["speech_recognition"]
    assert (
        classify("openai", {"id": "unknown-audio-transcribe"}, "openai")["profile"]
        is None
    )


@pytest.mark.parametrize("status", [401, 403, 429])
def test_upstream_failure_is_not_an_empty_success_or_a_browser_secret_echo(status):
    secret = secrets.token_urlsafe(24)
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"error": secret})

    with pytest.raises(CatalogFailure) as result:
        fetch_catalog("openai", secret, transport=httpx.MockTransport(respond))
    assert secret not in str(result.value)
    assert str(status) in str(result.value)
    assert len(calls) == 1


def test_empty_catalog_is_confirmed_and_repeating_pagination_is_rejected():
    secret = secrets.token_urlsafe(24)
    assert (
        fetch_catalog(
            "openai",
            secret,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": []})
            ),
        )
        == []
    )
    with pytest.raises(CatalogFailure, match="pagination"):
        fetch_catalog(
            "gemini",
            secret,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"models": [], "nextPageToken": "repeat"}
                )
            ),
        )


def test_malformed_gemini_generation_metadata_is_rejected_not_promoted():
    secret = secrets.token_urlsafe(24)
    with pytest.raises(CatalogFailure):
        fetch_catalog(
            "gemini",
            secret,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "models": [
                            {
                                "name": "models/gemini-3.8-flash",
                                "supportedGenerationMethods": "generateContent",
                            }
                        ]
                    },
                )
            ),
        )


def test_catalog_choice_registers_and_rereads_exact_profile_but_rejects_tampering_and_stale_connection(
    db, admin
):
    owner, connection_id = admin[0]["id"], uuid4().hex
    registry = Registry(db)
    store = CredentialStore(db, secrets.token_bytes(32))
    connection = registry.save_connection(
        owner, connection_id, revision=0, name="OpenAI", provider="openai"
    )
    connection = store.save(
        owner,
        connection_id,
        revision=connection["revision"],
        secret=secrets.token_urlsafe(24),
    )
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=store,
    )
    app.state.model_catalog_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": [{"id": "gpt-5.5"}]})
    )
    with TestClient(app) as client:
        login(client, admin)
        catalog = client.post(
            "/api/settings/serving-connections/" + connection_id + "/model-catalog",
            json={"connection_revision": connection["current_revision"]},
        ).json()
        selected = catalog["models"][0]
        payload = dict(
            revision=0,
            name="Discovered GPT",
            model=selected["id"],
            connection_id=connection_id,
            connection_revision=connection["current_revision"],
            discovery_token=selected["registration_token"],
            **selected["profile"],
        )
        mid = uuid4().hex
        response = client.put("/api/settings/registered-models/" + mid, json=payload)
        assert response.status_code == 200
        reread = client.get("/api/settings/registered-models").json()["models"]
        row = next(row for row in reread if row["id"] == mid)
        assert row["versions"]["1"]["model"] == selected["id"]
        assert (
            row["versions"]["1"]["connection_revision"]
            == connection["current_revision"]
        )
        assert row["versions"]["1"]["translation_supported"] is True
        assert "discovery_token" not in str(row)
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex,
                json={**payload, "model": "forged-other-model"},
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex,
                json={k: v for k, v in payload.items() if k != "discovery_token"},
            ).status_code
            == 422
        )
        # Existing identical model/connection/profile may be renamed without a fresh network query.
        rename = {k: v for k, v in payload.items() if k != "discovery_token"}
        assert (
            client.put(
                "/api/settings/registered-models/" + mid,
                json={**rename, "revision": 1, "name": "Renamed"},
            ).status_code
            == 200
        )
        store.save(
            owner,
            connection_id,
            revision=connection["revision"],
            secret=secrets.token_urlsafe(24),
        )
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex, json=payload
            ).status_code
            == 409
        )
        assert registry.model(owner, mid)["versions"]["1"]["name"] == "Discovered GPT"


@pytest.mark.parametrize("provider", ["gemini", "anthropic", "xai"])
def test_native_catalog_auth_pagination_and_capability_adapter_intersection(
    db, admin, provider
):
    owner, identity = admin[0]["id"], uuid4().hex
    registry = Registry(db)
    store = CredentialStore(db, secrets.token_bytes(32))
    saved = registry.save_connection(
        owner, identity, revision=0, name=provider, provider=provider
    )
    key = secrets.token_urlsafe(24)
    saved = store.save(owner, identity, revision=saved["revision"], secret=key)
    calls = []

    def respond(request):
        assert request.method == "GET" and not request.content
        assert key not in str(request.url)
        calls.append((request.url.path, dict(request.url.params)))
        if provider == "gemini":
            assert (
                request.headers["x-goog-api-key"] == key
                and "authorization" not in request.headers
            )
            assert request.url.path == "/v1beta/models"
            if request.url.params.get("pageToken"):
                return httpx.Response(
                    200,
                    json={
                        "models": [
                            {
                                "name": "models/unknown-audio-live",
                                "supportedGenerationMethods": ["generateContent"],
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-3.8-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "page-two",
                },
            )
        if provider == "anthropic":
            assert request.headers["Authorization"] == "Bearer " + key
            assert request.headers["anthropic-version"] == "2026-10-21"
            assert request.url.path == "/v1/models"
            if request.url.params.get("after_id"):
                return httpx.Response(
                    200,
                    json={
                        "data": [{"id": "claude-unknown", "capabilities": None}],
                        "has_more": False,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "claude-sonnet-4-6",
                            "capabilities": {
                                "image_input": {"supported": True},
                                "structured_outputs": {"supported": True},
                            },
                        }
                    ],
                    "has_more": True,
                    "last_id": "claude-sonnet-4-6",
                },
            )
        assert request.headers["Authorization"] == "Bearer " + key
        if request.url.path == "/v1/models":
            return httpx.Response(
                200, json={"data": [{"id": "grok-4"}, {"id": "grok-imagine-image"}]}
            )
        assert request.url.path == "/v1/language-models"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "id": "grok-4",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                        "aliases": [],
                    }
                ]
            },
        )

    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=store,
    )
    app.state.model_catalog_transport = httpx.MockTransport(respond)
    with TestClient(app) as client:
        login(client, admin)
        response = client.post(
            "/api/settings/serving-connections/" + identity + "/model-catalog",
            json={"connection_revision": saved["current_revision"]},
        )
        assert response.status_code == 200
        assert key not in response.text
        result = response.json()
        assert result["complete"] is True and len(calls) == 2
        assert len(result["models"]) == 2
        first, unknown = result["models"]
        assert first["profile"] is not None and first["evidence"]
        assert first["runtime_uses"] == (
            [] if provider == "anthropic" else ["translation"]
        )
        assert unknown["profile"] is None
        assert not first["profile"]["capabilities"].count("speech_recognition")


def test_named_legacy_endpoint_and_encrypted_key_reference_are_preserved_without_query(
    db, admin
):
    from video_service.model_catalog import ModelCatalog
    from video_service.model_endpoints import canonical_hash

    owner, identity = admin[0]["id"], uuid4().hex
    historical = {
        "name": "Historical separate endpoint",
        "provider": "gemini",
        "protocol": "openai_compatible",
        "endpoint": "https://custom.invalid/private/v1",
        "credential_ref": None,
    }
    # Initial historical fixture insert, never an UPDATE to an immutable revision.
    with db.connection() as sql:
        sql.execute(
            "INSERT INTO serving_connections(owner_id,id,revision,state_revision) VALUES (%s,%s,1,1)",
            (owner, identity),
        )
        sql.execute(
            "INSERT INTO connection_revisions(owner_id,connection_id,revision,name,provider,protocol,endpoint,credential_ref,sha256) VALUES (%s,%s,1,%s,%s,%s,%s,NULL,%s)",
            (
                owner,
                identity,
                historical["name"],
                historical["provider"],
                historical["protocol"],
                historical["endpoint"],
                canonical_hash(historical),
            ),
        )
    store = CredentialStore(db, secrets.token_bytes(32))
    secret = secrets.token_urlsafe(24)
    store.save(owner, identity, revision=1, secret=secret)
    registry = Registry(db)
    renamed = registry.save_connection(
        owner, identity, revision=2, name="Renamed only", provider="gemini"
    )
    assert (
        renamed["endpoint"] == historical["endpoint"]
        and renamed["protocol"] == historical["protocol"]
    )
    assert (
        renamed["address_mode"] == "legacy_preserved"
        and renamed["credential"] == "reference_set"
    )
    with db.connection() as sql:
        original = sql.execute(
            "SELECT sha256 FROM connection_revisions WHERE owner_id=%s AND connection_id=%s AND revision=1",
            (owner, identity),
        ).fetchone()
        row = registry._connection(sql, owner, identity)[1]
    assert original["sha256"] == canonical_hash(historical)
    assert store.resolve(owner, identity, row["credential_ref"]) == secret
    calls = []
    with pytest.raises(CatalogFailure):
        ModelCatalog(
            registry, store, transport=httpx.MockTransport(lambda r: calls.append(r))
        ).query(owner, identity, renamed["current_revision"])
    assert calls == []


def test_official_query_preserves_auth_origin_csrf_boundaries(db, admin):
    store = CredentialStore(db, secrets.token_bytes(32))
    connection = Registry(db).save_connection(
        admin[0]["id"], uuid4().hex, revision=0, name="OpenAI", provider="openai"
    )
    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=store,
    )
    calls = []
    app.state.model_catalog_transport = httpx.MockTransport(lambda r: calls.append(r))
    path = "/api/settings/serving-connections/" + connection["id"] + "/model-catalog"
    with TestClient(app) as client:
        assert client.post(path, json={"connection_revision": 1}).status_code == 401
        login(client, admin)
        assert (
            client.post(
                path, json={"connection_revision": 1}, headers={"X-CSRF-Token": ""}
            ).status_code
            == 403
        )
        assert (
            client.post(
                path,
                json={"connection_revision": 1},
                headers={"Origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        response = client.post(path, json={"connection_revision": 1})
        assert response.status_code == 422 and "키가 없습니다" in response.text
    assert calls == []


def test_owner_bound_catalog_token_does_not_cross_connections_or_expiry(
    db, admin, monkeypatch
):
    import video_service.postgres.credentials as module

    store = CredentialStore(db, secrets.token_bytes(32))
    owner, identity = admin[0]["id"], uuid4().hex
    token = store.seal_catalog_entry(owner, identity, {"model": "metadata-only"})
    with pytest.raises(ValueError):
        store.open_catalog_entry(owner, uuid4().hex, token)
    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 901)
    with pytest.raises(ValueError):
        store.open_catalog_entry(owner, identity, token)


@pytest.mark.parametrize(
    "provider,protocol,endpoint",
    [
        ("openai", "openai", "https://api.openai.com/v1"),
        ("gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta"),
        ("anthropic", "anthropic", "https://api.anthropic.com"),
        ("xai", "openai", "https://api.x.ai/v1"),
    ],
)
def test_named_provider_uses_server_contract_without_client_url_or_protocol(
    db, admin, provider, protocol, endpoint
):
    owner = admin[0]["id"]
    with app_client(db) as client:
        login(client, admin)
        identity = uuid4().hex
        response = client.put(
            "/api/settings/serving-connections/" + identity,
            json={"revision": 0, "name": provider, "provider": provider},
        )
        assert response.status_code == 200
        result = response.json()
        assert (result["provider"], result["protocol"], result["endpoint"]) == (
            provider,
            protocol,
            endpoint,
        )
        assert Registry(db).connection(owner, identity)["current_revision"] == 1
