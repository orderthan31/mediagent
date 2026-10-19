-- Explicit renewal runtime, never applied at startup. Existing legacy data untouched.
CREATE TABLE source_uploads (
 owner_id text NOT NULL REFERENCES accounts(id),
 id text NOT NULL CHECK(id ~ '^[a-f0-9]{32}$'),
 request_id text NOT NULL,
 request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[a-f0-9]{64}$'),
 filename text NOT NULL,
 expected_size bigint NOT NULL CHECK(expected_size > 0 AND expected_size <= 268435456),
 uploaded_bytes bigint NOT NULL DEFAULT 0 CHECK(uploaded_bytes >= 0),
 asset_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,id), UNIQUE(owner_id,request_id),
 FOREIGN KEY(owner_id,asset_id) REFERENCES assets(owner_id,id)
);
CREATE TABLE source_upload_parts (
 owner_id text NOT NULL, upload_id text NOT NULL, byte_offset bigint NOT NULL CHECK(byte_offset >= 0),
 reference jsonb NOT NULL CHECK(jsonb_typeof(reference)='object'),
 PRIMARY KEY(owner_id,upload_id,byte_offset),
 FOREIGN KEY(owner_id,upload_id) REFERENCES source_uploads(owner_id,id)
);
ALTER TABLE workflow_revisions ADD COLUMN provenance jsonb NOT NULL DEFAULT '{"kind":"editor_save"}';
ALTER TABLE jobs ADD COLUMN creation_request_id text;
ALTER TABLE jobs ADD COLUMN creation_sha256 text;
ALTER TABLE jobs ADD COLUMN cancel_requested boolean NOT NULL DEFAULT false;
ALTER TABLE jobs ADD COLUMN active_claim_id text;
ALTER TABLE jobs ADD COLUMN recovery_ready boolean NOT NULL DEFAULT true;
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check CHECK(status IN
 ('draft','waiting','running','review_required','completed','failed','cancelled','cancelling'));
CREATE UNIQUE INDEX jobs_creation_idempotent ON jobs(owner_id,creation_request_id) WHERE creation_request_id IS NOT NULL;
ALTER TABLE node_runs DROP CONSTRAINT node_runs_status_check;
ALTER TABLE node_runs ADD CONSTRAINT node_runs_status_check CHECK(status IN
 ('waiting','running','review_required','completed','failed','cancelled','quarantined','skipped','blocked'));
ALTER TABLE node_runs ADD COLUMN inputs jsonb NOT NULL DEFAULT '{}';
ALTER TABLE node_runs ADD COLUMN options jsonb NOT NULL DEFAULT '{}';
ALTER TABLE node_runs ADD COLUMN node_type text;
ALTER TABLE node_runs ADD COLUMN request jsonb;
ALTER TABLE node_runs ADD COLUMN request_sha256 text;
ALTER TABLE node_runs ADD COLUMN started_at timestamptz;
ALTER TABLE node_runs ADD COLUMN completed_at timestamptz;
ALTER TABLE node_runs ADD COLUMN claim_id text;
ALTER TABLE execution_claims ADD COLUMN request_id text;
ALTER TABLE execution_claims ADD COLUMN request_sha256 text;
CREATE UNIQUE INDEX claims_request_idempotent ON execution_claims(owner_id,request_id) WHERE request_id IS NOT NULL;
ALTER TABLE execution_consents ADD COLUMN request_sha256 text;
CREATE TABLE review_revisions (
 owner_id text NOT NULL, review_id text NOT NULL, revision integer NOT NULL CHECK(revision>0),
 draft jsonb NOT NULL, sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,review_id,revision),
 FOREIGN KEY(owner_id,review_id) REFERENCES review_tasks(owner_id,id)
);
CREATE TRIGGER review_revision_immutable BEFORE UPDATE OR DELETE ON review_revisions
 FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE FUNCTION reject_job_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
 OR NEW.asset_id IS DISTINCT FROM OLD.asset_id OR NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
 OR NEW.workflow_revision IS DISTINCT FROM OLD.workflow_revision THEN
  RAISE EXCEPTION 'Execution snapshot is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER job_snapshot_immutable BEFORE UPDATE ON jobs
 FOR EACH ROW EXECUTE FUNCTION reject_job_snapshot_mutation();
CREATE TABLE result_quarantine (
 owner_id text NOT NULL, job_id text NOT NULL, node_run_id text NOT NULL,
 message_sha256 text NOT NULL, reason text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,job_id,node_run_id,message_sha256),
 FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE TABLE agent_deliveries (
 owner_id text NOT NULL, job_id text NOT NULL, node_run_id text NOT NULL,
 command_sha256 text NOT NULL CHECK(command_sha256 ~ '^[a-f0-9]{64}$'),
 status text NOT NULL CHECK(status IN ('started','completed')),
 result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,job_id,node_run_id),
 FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
