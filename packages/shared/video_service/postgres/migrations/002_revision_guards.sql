-- Append-only configuration snapshots and a transactional message boundary.
CREATE FUNCTION reject_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Configuration revisions are immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER connection_revision_immutable BEFORE UPDATE OR DELETE ON connection_revisions
FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TRIGGER model_revision_immutable BEFORE UPDATE OR DELETE ON model_revisions
FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TRIGGER workflow_revision_immutable BEFORE UPDATE OR DELETE ON workflow_revisions
FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TABLE message_outbox (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    owner_id text NOT NULL REFERENCES accounts(id),
    aggregate_id text NOT NULL,
    message_type text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
CREATE INDEX outbox_unpublished ON message_outbox(created_at,id) WHERE published_at IS NULL;
CREATE TABLE message_inbox (
    consumer text NOT NULL,
    message_id text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(consumer,message_id)
);
