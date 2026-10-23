"""Real isolated PG/ASGI registry checks; provider HTTP is controlled and GET-only."""

import hashlib
import json
import secrets
from uuid import uuid4

import httpx
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_foundation import admin as _admin
from test_foundation import login
from test_original_upload_policy import db as _db
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.registry import Registry

db, admin = _db, _admin


def test_new_pro_purpose_saves_normally_without_changing_existing_model_key_or_proof_contract(
    db, admin
):
    owner = admin[0]["id"]
    cid = uuid4().hex
    registry = Registry(db)
    credentials = CredentialStore(db, secrets.token_bytes(32))
    connection = registry.save_connection(
        owner, cid, revision=0, name="isolated Gemini", provider="gemini"
    )
    key = secrets.token_urlsafe(24)
    connection = credentials.save(
        owner, cid, revision=connection["revision"], secret=key
    )
    calls = []
    raw = [
        {"name": "models/" + name, "supportedGenerationMethods": ["generateContent"]}
        for name in [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-3.8-flash-tts",
            "gemini-unverified-future-pro",
        ]
    ]

    def transport(request):
        assert (
            request.method == "GET"
            and request.url.host == "generativelanguage.googleapis.com"
        )
        assert request.headers["x-goog-api-key"] == key and not request.content
        calls.append(request.url.path)
        return httpx.Response(200, json={"models": raw})

    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=credentials,
    )
    app.state.model_catalog_transport = httpx.MockTransport(transport)
    with TestClient(app) as client:
        login(client, admin)
        catalog = client.post(
            "/api/settings/serving-connections/" + cid + "/model-catalog",
            json={"connection_revision": connection["current_revision"]},
        )
        assert catalog.status_code == 200 and key not in catalog.text
        discovered = {m["id"]: m for m in catalog.json()["models"]}
        assert discovered["gemini-2.5-pro"]["profile"] is not None
        assert discovered["gemini-2.5-pro"]["runtime_uses"] == ["translation"]
        assert "registration_token" not in discovered["gemini-3.8-flash-tts"]
        assert "registration_token" not in discovered["gemini-unverified-future-pro"]

        def payload(model, name):
            selected = discovered[model]
            return dict(
                revision=0,
                name=name,
                model=model,
                connection_id=cid,
                connection_revision=connection["current_revision"],
                discovery_token=selected["registration_token"],
                **selected["profile"],
            )

        old_id, new_id = uuid4().hex, uuid4().hex
        assert (
            client.put(
                "/api/settings/registered-models/" + old_id,
                json=payload("gemini-2.5-flash", "existing frozen Flash"),
            ).status_code
            == 200
        )
        before = next(
            m
            for m in client.get("/api/settings/registered-models").json()["models"]
            if m["id"] == old_id
        )

        def immutable_credentials():
            with db.connection() as c:
                data = {
                    table: c.execute(
                        "SELECT to_jsonb(t) AS row FROM " + table + " t"
                    ).fetchall()
                    for table in [
                        "serving_connections",
                        "connection_revisions",
                        "provider_credentials",
                    ]
                }
            return hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode()
            ).hexdigest()

        original_credentials = immutable_credentials()
        pro = payload("gemini-2.5-pro", "Pro text candidate")
        assert (
            client.put(
                "/api/settings/registered-models/" + new_id, json=pro
            ).status_code
            == 200
        )
        models = client.get("/api/settings/registered-models").json()["models"]
        saved = next(m for m in models if m["id"] == new_id)
        assert (
            saved["current_revision"] == 1
            and saved["versions"]["1"]["model"] == "gemini-2.5-pro"
        )
        assert saved["versions"]["1"]["translation_supported"] is True
        assert not saved["versions"]["1"].get("transcription_supported", False)
        assert next(m for m in models if m["id"] == old_id) == before
        assert immutable_credentials() == original_credentials
        with db.connection() as c:
            _, private_connection = registry._connection(c, owner, cid)
        assert (
            credentials.resolve(owner, cid, private_connection["credential_ref"]) == key
        )
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex,
                json={**pro, "model": "forged-model"},
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex,
                json={k: v for k, v in pro.items() if k != "discovery_token"},
            ).status_code
            == 422
        )
        forged = {
            **pro,
            "model_types": ["speech_recognition"],
            "capabilities": ["speech_recognition"],
            "input_modalities": ["audio"],
        }
        assert (
            client.put(
                "/api/settings/registered-models/" + uuid4().hex, json=forged
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/settings/registered-models/" + new_id,
                json={**pro, "name": "stale rename"},
            ).status_code
            == 409
        )
        assert immutable_credentials() == original_credentials
        assert len(client.get("/api/settings/registered-models").json()["models"]) == 2
        assert calls == ["/v1beta/models"]
    with db.connection() as c:
        assert (
            c.execute("SELECT to_regclass('video_preview_jobs') AS x").fetchone()["x"]
            is None
        )


def test_no_key_query_failure_and_confirmed_empty_stay_separate_from_model_classification(
    db, admin
):
    owner = admin[0]["id"]
    cid = uuid4().hex
    registry = Registry(db)
    credentials = CredentialStore(db, secrets.token_bytes(32))
    connection = registry.save_connection(
        owner, cid, revision=0, name="isolated key states", provider="gemini"
    )
    calls = []
    mode = {"status": 401}
    key = secrets.token_urlsafe(24)

    def transport(request):
        assert request.method == "GET"
        calls.append(request.url.path)
        return httpx.Response(
            mode["status"],
            json={"models": []} if mode["status"] == 200 else {"error": key},
        )

    app = create_app(
        db,
        allowed_origins=("http://testserver",),
        secure_cookies=False,
        credential_store=credentials,
    )
    app.state.model_catalog_transport = httpx.MockTransport(transport)
    with TestClient(app) as client:
        login(client, admin)
        url = "/api/settings/serving-connections/" + cid + "/model-catalog"
        absent = client.post(
            url, json={"connection_revision": connection["current_revision"]}
        )
        assert absent.status_code == 422 and "API 키" in absent.text and calls == []
        connection = credentials.save(
            owner, cid, revision=connection["revision"], secret=key
        )
        for status in [401, 403, 429]:
            mode["status"] = status
            failed = client.post(
                url, json={"connection_revision": connection["current_revision"]}
            )
            assert (
                failed.status_code == 422
                and str(status) in failed.text
                and key not in failed.text
            )
            assert "models" not in failed.json()
        mode["status"] = 200
        empty = client.post(
            url, json={"connection_revision": connection["current_revision"]}
        )
        assert (
            empty.status_code == 200
            and empty.json()["complete"]
            and empty.json()["models"] == []
        )
        assert len(calls) == 4
        with db.connection() as c:
            assert (
                c.execute("SELECT count(*) AS n FROM registered_models").fetchone()["n"]
                == 0
            )
