"""Disposable PG + injected model wire only; never a provider/model network call."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from app.bootstrap import generate
from app.renewal import create_app
from fastapi.testclient import TestClient
from test_foundation import admin as _admin
from test_foundation import db as _db
from test_foundation import login
from test_model_profile import profile
from video_service.postgres import Conflict
from video_service.postgres.accounts import Accounts
from video_service.postgres.credentials import CredentialStore, CredentialUnavailable
from video_service.postgres.registry import Registry

admin, db = _admin, _db


def connection(db, owner, endpoint="https://synthetic.invalid/v1"):
    cid = uuid4().hex
    Registry(db).save_connection(
        owner,
        cid,
        revision=0,
        name="Synthetic",
        provider="openai_compatible",
        protocol="openai_compatible",
        endpoint=endpoint,
    )
    return cid


def test_admin_write_only_secret_cas_revoke_and_no_key_echo(db, admin):
    owner, key, secret = admin[0]["id"], os.urandom(32), "synthetic-write-only-sentinel"
    cid = connection(db, owner)
    store = CredentialStore(db, key)
    with TestClient(
        create_app(
            db,
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            credential_store=store,
        )
    ) as client:
        target = "/api/settings/serving-connections/" + cid + "/credential"
        assert (
            client.put(target, json={"revision": 1, "secret": secret}).status_code
            == 401
        )
        login(client, admin)
        assert (
            client.put(
                target,
                json={"revision": 1, "secret": secret},
                headers={"X-CSRF-Token": ""},
            ).status_code
            == 403
        )
        saved = client.put(target, json={"revision": 1, "secret": secret})
        assert (
            saved.status_code == 200 and saved.json()["credential"] == "reference_set"
        )
        assert secret not in saved.text
        assert (
            client.put(target, json={"revision": 1, "secret": secret}).status_code
            == 409
        )
        assert (
            client.put(
                target, json={"revision": 2, "secret": secret, "extra": secret}
            ).status_code
            == 422
        )
        assert secret not in client.get("/api/settings/serving-connections").text
        with db.connection() as sql:
            credential = sql.execute(
                "SELECT * FROM provider_credentials WHERE owner_id=%s", (owner,)
            ).fetchone()
            ref = sql.execute(
                "SELECT credential_ref FROM connection_revisions WHERE owner_id=%s AND connection_id=%s AND revision=2",
                (owner, cid),
            ).fetchone()["credential_ref"]
            assert secret.encode() not in bytes(
                credential["ciphertext"]
            ) and ref.startswith("db:")
        assert store.resolve(owner, cid, ref) == secret
        assert (
            client.put(target, json={"revision": 2, "secret": None}).status_code == 200
        )
        with pytest.raises(CredentialUnavailable):
            store.resolve(owner, cid, ref)
        Accounts(db).create("ordinary", admin[1], actor_id=owner)
        client.post("/api/auth/logout")
        login(client, ({"username": "ordinary"}, admin[1]))
        assert (
            client.put(target, json={"revision": 3, "secret": secret}).status_code
            == 403
        )


def test_saved_revision_resolves_db_values_never_environment(db, admin, monkeypatch):
    owner = admin[0]["id"]
    cid = connection(db, owner)
    registry, store = Registry(db), CredentialStore(db, os.urandom(32))
    store.save(owner, cid, revision=1, secret="synthetic-db-key")
    mid = uuid4().hex
    registry.save_model(
        owner,
        mid,
        revision=0,
        name="Synthetic text",
        model="db-selected-model",
        connection_id=cid,
        connection_revision=2,
        **profile(),
    )
    # Conflicting app settings must never select the destination, model or key.
    for name, value in {
        "OPENAI_API_KEY": "synthetic-env-key",
        "OPENAI_BASE_URL": "https://wrong.invalid",
        "LLM_MODEL": "wrong-env-model",
    }.items():
        monkeypatch.setenv(name, value)
    requests = []

    def wire(request):
        requests.append(request)
        assert str(request.url) == "https://synthetic.invalid/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-db-key"
        assert json.loads(request.content)["model"] == "db-selected-model"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "synthetic response"},
                    }
                ]
            },
        )

    registry.save_model(
        owner,
        mid,
        revision=1,
        name="Later model",
        model="new-model",
        connection_id=cid,
        connection_revision=2,
        **profile(),
    )
    assert (
        store.chat(
            owner,
            mid,
            1,
            [{"role": "user", "content": "Synthetic input"}],
            transport=httpx.MockTransport(wire),
            approved_origins={"https://synthetic.invalid"},
        )
        == "synthetic response"
    )
    assert len(requests) == 1
    with pytest.raises(ValueError):
        store.chat(
            owner,
            mid,
            1,
            [{"role": "user", "content": "Synthetic"}],
            transport=None,
            approved_origins={"https://synthetic.invalid"},
        )
    store.save(owner, cid, revision=2, secret=None)
    with pytest.raises(CredentialUnavailable):
        store.chat(
            owner,
            mid,
            1,
            [{"role": "user", "content": "Synthetic"}],
            transport=httpx.MockTransport(wire),
            approved_origins={"https://synthetic.invalid"},
        )
    assert len(requests) == 1


def test_cipher_binding_wrong_key_tamper_and_metadata_changes(db, admin):
    owner = admin[0]["id"]
    cid = connection(db, owner)
    store = CredentialStore(db, os.urandom(32))
    store.save(owner, cid, revision=1, secret="synthetic-secret")
    with db.connection() as sql:
        ref = sql.execute(
            "SELECT credential_ref FROM connection_revisions WHERE owner_id=%s AND connection_id=%s AND revision=2",
            (owner, cid),
        ).fetchone()["credential_ref"]
    for resolver, args in [
        (CredentialStore(db, os.urandom(32)), (owner, cid, ref)),
        (store, (uuid4().hex, cid, ref)),
        (store, (owner, uuid4().hex, ref)),
        (store, (owner, cid, "env:OPENAI_API_KEY")),
    ]:
        with pytest.raises(CredentialUnavailable):
            resolver.resolve(*args)
    saved = Registry(db).save_connection(
        owner,
        cid,
        revision=2,
        name="Renamed",
        provider="openai_compatible",
        protocol="openai_compatible",
        endpoint="https://synthetic.invalid/v1",
    )
    assert saved["credential"] == "reference_set"
    saved = Registry(db).save_connection(
        owner,
        cid,
        revision=3,
        name="Changed destination",
        provider="openai_compatible",
        protocol="openai_compatible",
        endpoint="https://other.invalid/v1",
    )
    assert saved["credential"] == "not_set"
    with db.connection() as sql:
        sql.execute(
            "UPDATE provider_credentials SET ciphertext=%s WHERE owner_id=%s",
            (b"x" * 40, owner),
        )
    with pytest.raises(CredentialUnavailable):
        store.resolve(owner, cid, ref)


def test_concurrent_credentials_exactly_one_cas_revision(db, admin):
    owner = admin[0]["id"]
    cid = connection(db, owner)
    store = CredentialStore(db, os.urandom(32))

    def save(index):
        try:
            return store.save(owner, cid, revision=1, secret="synthetic-" + str(index))
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [1, 2]))
    assert sum(row is not None for row in results) == 1
    with db.connection() as sql:
        assert (
            sql.execute(
                "SELECT count(*) AS n FROM provider_credentials WHERE owner_id=%s",
                (owner,),
            ).fetchone()["n"]
            == 1
        )


def test_missing_master_key_never_uses_environment_and_invalid_secret_is_bounded(
    db, admin, tmp_path, monkeypatch
):
    owner = admin[0]["id"]
    cid = connection(db, owner)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-environment-value")
    with pytest.raises(CredentialUnavailable):
        CredentialStore.from_file(db, tmp_path / "absent")
    with TestClient(
        create_app(db, allowed_origins=("http://testserver",), secure_cookies=False)
    ) as client:
        login(client, admin)
        response = client.put(
            "/api/settings/serving-connections/" + cid + "/credential",
            json={"revision": 1, "secret": "synthetic"},
        )
        assert response.status_code == 503
    store = CredentialStore(db, os.urandom(32))
    for secret in ("", "x" * 4097, "bad\r\nheader", 123):
        with pytest.raises(ValueError):
            store.save(owner, cid, revision=1, secret=secret)


def test_new_bootstrap_private_compartments_and_no_overwrite(tmp_path):
    target = tmp_path / "private"
    generate(target, "https://synthetic.invalid")
    assert len((target / "api" / "credential-master.key").read_bytes()) == 32
    assert not (target / "agent" / "analyze" / "database-dsn").exists()
    assert not (target / "agent" / "analyze" / "credential-master.key").exists()
    assert not (target / "api" / "private.key").exists()
    assert (target / "offline-ca" / "ca.key").exists()
    before = (target / "api" / "credential-master.key").read_bytes()
    with pytest.raises(FileExistsError):
        generate(target, "https://synthetic.invalid")
    assert (target / "api" / "credential-master.key").read_bytes() == before
