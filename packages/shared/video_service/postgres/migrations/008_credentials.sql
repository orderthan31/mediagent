-- Explicit migration only. Existing env references are retained but never resolved.
ALTER TABLE connection_revisions DROP CONSTRAINT connection_revisions_credential_ref_check;
ALTER TABLE connection_revisions ADD CONSTRAINT connection_revisions_credential_ref_check
    CHECK (credential_ref IS NULL OR credential_ref ~ '^db:[a-f0-9]{32}$') NOT VALID;
CREATE TABLE provider_credentials (
    owner_id text NOT NULL,
    connection_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[a-f0-9]{32}$'),
    ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 29 AND 8192),
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    PRIMARY KEY(owner_id,id),
    FOREIGN KEY(owner_id,connection_id) REFERENCES serving_connections(owner_id,id)
);
CREATE INDEX provider_credentials_connection ON provider_credentials(owner_id,connection_id);
