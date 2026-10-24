"""Normal authenticated PG registration; synthetic key, controlled catalog GET only."""

import copy
import secrets
from uuid import uuid4

import httpx
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_foundation import login
from test_gemini_catalog_registry import admin as _admin
from test_gemini_catalog_registry import db as _db
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.registry import Registry

db, admin = _db, _admin


def test_explicit_gemini_audio_revision_has_own_proof_and_preserves_previous_profile(
    db, admin
):
    owner = admin[0]["id"]
    registry, credentials = Registry(db), CredentialStore(db, secrets.token_bytes(32))
    cid, mid = uuid4().hex, uuid4().hex
    conn = registry.save_connection(
        owner, cid, revision=0, name="isolated timed Gemini", provider="gemini"
    )
    secret = secrets.token_urlsafe(32)
    conn = credentials.save(owner, cid, revision=conn["revision"], secret=secret)
    methods = []

    def transport(request):
        assert (
            request.method == "GET"
            and request.url.host == "generativelanguage.googleapis.com"
        )
        assert request.headers["x-goog-api-key"] == secret
        methods.append(request.method)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    }
                ]
            },
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
        catalog = client.post(
            "/api/settings/serving-connections/" + cid + "/model-catalog",
            json={"connection_revision": conn["current_revision"]},
        )
        assert catalog.status_code == 200 and secret not in catalog.text
        row = catalog.json()["models"][0]
        variant = row["profile_variants"]["transcription"]
        assert isinstance(variant.get("registration_token"), str), (
            "audio compatibility needs its own profile-bound catalog proof"
        )
        base = dict(
            revision=0,
            name="existing Gemini translation",
            model=row["id"],
            connection_id=cid,
            connection_revision=conn["current_revision"],
            discovery_token=row["registration_token"],
            **row["profile"],
        )
        assert (
            client.put("/api/settings/registered-models/" + mid, json=base).status_code
            == 200
        )
        old = client.get("/api/settings/registered-models").json()["models"][0]
        frozen = copy.deepcopy(old["versions"]["1"])
        asr = {
            **base,
            **variant["profile"],
            "revision": old["revision"],
            "name": "explicit Gemini audio compatibility",
        }
        assert (
            client.put("/api/settings/registered-models/" + mid, json=asr).status_code
            == 422
        ), "text proof must not authorize speech capability"
        asr["discovery_token"] = variant["registration_token"]
        saved = client.put("/api/settings/registered-models/" + mid, json=asr)
        assert saved.status_code == 200
        reread = client.get("/api/settings/registered-models").json()["models"][0]
        assert reread["current_revision"] == 2
        assert reread["versions"]["1"] == frozen
        assert reread["versions"]["2"]["transcription_supported"] is True
        assert reread["versions"]["2"]["translation_supported"] is True
        assert reread["versions"]["1"]["transcription_supported"] is False
        assert (
            client.put("/api/settings/registered-models/" + mid, json=asr).status_code
            == 409
        )
        assert registry.connection(owner, cid) == conn
        assert methods == ["GET"]
