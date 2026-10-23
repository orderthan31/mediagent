-- Durable derivative jobs are sidecars: never mutate tickets/accepted receipts/manifests.
CREATE TABLE video_preview_jobs (
    id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
    request_key text NOT NULL UNIQUE CHECK (request_key ~ '^[a-f0-9]{64}$'),
    requested_by text NOT NULL REFERENCES accounts(id),
    storage_owner_id text NOT NULL REFERENCES accounts(id),
    subject jsonb NOT NULL,
    source_ref jsonb NOT NULL,
    profile jsonb NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','ready','cancelled','failed','held')),
    stage text NOT NULL DEFAULT 'queued' CHECK(stage IN ('queued','loading','encoding','verifying','finished','held')),
    cancel_requested boolean NOT NULL DEFAULT false,
    worker_instance text,
    claim_count integer NOT NULL DEFAULT 0 CHECK (claim_count BETWEEN 0 AND 1),
    output_ref jsonb,
    output_media jsonb,
    verified_at timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CHECK (state <> 'ready' OR (output_ref IS NOT NULL AND output_media IS NOT NULL AND verified_at IS NOT NULL AND NOT cancel_requested))
);
CREATE INDEX video_preview_pending ON video_preview_jobs(created_at,id) WHERE state='queued';

CREATE FUNCTION preserve_video_preview_contract() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id,NEW.request_key,NEW.requested_by,NEW.storage_owner_id,NEW.subject,NEW.source_ref,NEW.profile,NEW.created_at)
       IS DISTINCT FROM
       (OLD.id,OLD.request_key,OLD.requested_by,OLD.storage_owner_id,OLD.subject,OLD.source_ref,OLD.profile,OLD.created_at) THEN
        RAISE EXCEPTION 'immutable_video_preview_contract';
    END IF;
    IF OLD.output_ref IS NOT NULL AND (NEW.output_ref,NEW.output_media,NEW.verified_at)
       IS DISTINCT FROM (OLD.output_ref,OLD.output_media,OLD.verified_at) THEN
        RAISE EXCEPTION 'immutable_video_preview_output';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER video_preview_contract_immutable BEFORE UPDATE ON video_preview_jobs
    FOR EACH ROW EXECUTE FUNCTION preserve_video_preview_contract();
