-- State CAS changes independently from immutable configuration revision numbers.
ALTER TABLE serving_connections ADD COLUMN state_revision integer NOT NULL DEFAULT 0 CHECK (state_revision >= 0);
UPDATE serving_connections SET state_revision = revision;
ALTER TABLE registered_models ADD COLUMN state_revision integer NOT NULL DEFAULT 0 CHECK (state_revision >= 0);
UPDATE registered_models SET state_revision = revision;
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE INDEX connections_owner ON serving_connections(owner_id,id);
CREATE INDEX models_owner ON registered_models(owner_id,id);
