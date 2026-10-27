-- Explicit opt-in for a fresh job only; no historical enrollment or queue scan.
CREATE TABLE model_role_enrollments (
 owner_id text NOT NULL,job_id text NOT NULL,generation integer NOT NULL,
 snapshot_sha256 text NOT NULL,request_id text NOT NULL,request_sha256 text NOT NULL,
 response jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,job_id,generation),UNIQUE(owner_id,request_id),
 FOREIGN KEY(owner_id,job_id)REFERENCES jobs(owner_id,id)
);
CREATE TRIGGER model_role_enrollment_immutable BEFORE UPDATE OR DELETE ON model_role_enrollments FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TABLE model_role_controls (
 owner_id text NOT NULL,job_id text NOT NULL,attempt_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('cancel','artifact_recovery')),request_id text NOT NULL,
 packet jsonb NOT NULL,packet_sha256 text NOT NULL,
 phase text NOT NULL DEFAULT 'ready'CHECK(phase IN ('ready','sending','sent','unknown','acknowledged')),
 ack jsonb,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,job_id,attempt_id,kind,request_id),
 FOREIGN KEY(owner_id,job_id,attempt_id)REFERENCES node_runs(owner_id,job_id,id)
);
CREATE FUNCTION protect_model_role_control()RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.owner_id,NEW.job_id,NEW.attempt_id,NEW.kind,NEW.request_id,NEW.packet,NEW.packet_sha256)
 IS DISTINCT FROM ROW(OLD.owner_id,OLD.job_id,OLD.attempt_id,OLD.kind,OLD.request_id,OLD.packet,OLD.packet_sha256)
 OR (OLD.ack IS NOT NULL AND NEW.ack IS DISTINCT FROM OLD.ack)THEN
 RAISE EXCEPTION 'Role control identity is immutable' USING ERRCODE='23514';END IF;
 RETURN NEW;END;$$;
CREATE TRIGGER model_role_control_immutable BEFORE UPDATE ON model_role_controls FOR EACH ROW EXECUTE FUNCTION protect_model_role_control();
CREATE TRIGGER model_role_control_no_delete BEFORE DELETE ON model_role_controls FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
