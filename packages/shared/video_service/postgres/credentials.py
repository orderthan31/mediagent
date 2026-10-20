"""Administrator-managed encrypted DB credentials; never consult environment keys."""

import os
import re
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..model_endpoints import canonical_hash
from . import Conflict, Missing
from .registry import Registry, resource_id


class CredentialUnavailable(ValueError):
    pass


class CredentialStore:
    def __init__(self, database, key):
        if not isinstance(key, bytes) or len(key) != 32:
            raise CredentialUnavailable("credential_key_unavailable")
        self.database = database
        self._cipher = AESGCM(key)

    @classmethod
    def from_file(cls, database, path):
        try:
            key = Path(path).read_bytes()
            return cls(database, key)
        except (OSError, ValueError):
            raise CredentialUnavailable("credential_key_unavailable") from None

    def save(self, owner, connection_id, *, revision, secret):
        resource_id(owner)
        resource_id(connection_id)
        if secret is not None and (
            not isinstance(secret, str)
            or not 1 <= len(secret) <= 4096
            or any(ord(c) < 32 or ord(c) > 126 for c in secret)
        ):
            raise ValueError("invalid_credential")
        registry = Registry(self.database)
        with self.database.connection() as db:
            actor = db.execute(
                "SELECT 1 FROM accounts WHERE id=%s AND active AND role='admin' FOR SHARE",
                (owner,),
            ).fetchone()
            if not actor:
                raise PermissionError("administrator_required")
            db.execute(
                "SELECT 1 FROM serving_connections WHERE owner_id=%s AND id=%s FOR UPDATE",
                (owner, connection_id),
            )
            parent, row = registry._connection(db, owner, connection_id)
            if parent["state_revision"] != revision:
                raise Conflict("connection_revision_conflict")
            ref = None
            if secret is not None:
                identity = uuid4().hex
                nonce = os.urandom(12)
                aad = (
                    f"mideagent.provider.v1:{owner}:{connection_id}:{identity}".encode()
                )
                encrypted = nonce + self._cipher.encrypt(nonce, secret.encode(), aad)
                db.execute(
                    "INSERT INTO provider_credentials(owner_id,connection_id,id,ciphertext) VALUES (%s,%s,%s,%s)",
                    (owner, connection_id, identity, encrypted),
                )
                ref = "db:" + identity
            else:
                db.execute(
                    "UPDATE provider_credentials SET revoked_at=now() WHERE owner_id=%s AND connection_id=%s AND revoked_at IS NULL",
                    (owner, connection_id),
                )
            data = {k: row[k] for k in ("name", "provider", "protocol", "endpoint")}
            data["credential_ref"] = ref
            db.execute(
                "INSERT INTO connection_revisions(owner_id,connection_id,revision,name,provider,protocol,endpoint,credential_ref,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    owner,
                    connection_id,
                    parent["revision"] + 1,
                    row["name"],
                    row["provider"],
                    row["protocol"],
                    row["endpoint"],
                    ref,
                    canonical_hash(data),
                ),
            )
            db.execute(
                "UPDATE serving_connections SET revision=revision+1,state_revision=state_revision+1 WHERE owner_id=%s AND id=%s",
                (owner, connection_id),
            )
            return registry._public_connection(
                *registry._connection(db, owner, connection_id)
            )

    def resolve(self, owner, connection_id, reference):
        if not isinstance(reference, str) or not re.fullmatch(
            r"db:[a-f0-9]{32}", reference
        ):
            raise CredentialUnavailable("credential_unavailable")
        resource_id(owner)
        resource_id(connection_id)
        with self.database.connection() as db:
            row = db.execute(
                "SELECT pc.id,pc.ciphertext FROM provider_credentials pc JOIN serving_connections c ON c.owner_id=pc.owner_id AND c.id=pc.connection_id JOIN accounts a ON a.id=pc.owner_id WHERE pc.owner_id=%s AND pc.connection_id=%s AND pc.id=%s AND pc.revoked_at IS NULL AND c.active AND a.active AND a.role='admin'",
                (owner, connection_id, reference[3:]),
            ).fetchone()
        if not row:
            raise CredentialUnavailable("credential_unavailable")
        try:
            raw = bytes(row["ciphertext"])
            aad = f"mideagent.provider.v1:{owner}:{connection_id}:{row['id']}".encode()
            return self._cipher.decrypt(raw[:12], raw[12:], aad).decode()
        except (InvalidTag, ValueError, UnicodeError):
            raise CredentialUnavailable("credential_unavailable") from None

    def model(self, owner, model_id, revision):
        resource_id(owner)
        resource_id(model_id)
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid_model_revision")
        with self.database.connection() as db:
            row = db.execute(
                "SELECT mr.*,cr.endpoint,cr.protocol,cr.credential_ref FROM model_revisions mr JOIN registered_models m ON m.owner_id=mr.owner_id AND m.id=mr.model_id JOIN serving_connections c ON c.owner_id=mr.owner_id AND c.id=mr.connection_id JOIN connection_revisions cr ON cr.owner_id=mr.owner_id AND cr.connection_id=mr.connection_id AND cr.revision=mr.connection_revision WHERE mr.owner_id=%s AND mr.model_id=%s AND mr.revision=%s AND m.active AND c.active AND EXISTS (SELECT 1 FROM accounts a WHERE a.id=mr.owner_id AND a.active AND a.role='admin')",
                (owner, model_id, revision),
            ).fetchone()
        if not row:
            raise Missing("model_unavailable")
        return row

    def chat(self, owner, model_id, revision, messages, *, transport, approved_origins):
        from ..model_endpoints import OpenAITextAdapter

        row = self.model(owner, model_id, revision)
        if (
            row["protocol"] not in ("openai", "openai_compatible")
            or "text_generation" not in row["capabilities"]
        ):
            raise ValueError("model_adapter_unavailable")
        key = (
            self.resolve(owner, row["connection_id"], row["credential_ref"])
            if row["credential_ref"]
            else None
        )
        adapter = OpenAITextAdapter(
            row["endpoint"],
            transport=transport,
            approved_origins=approved_origins,
            api_key=key,
        )
        try:
            return adapter.chat(row["remote_model"], messages)
        finally:
            adapter.close()
