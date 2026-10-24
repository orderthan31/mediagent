-- Source candidate only. Separate model-free artifact recovery; no source rewrites or GRANT.
CREATE TABLE projection_recoveries (
 owner_id text NOT NULL,
 job_id text NOT NULL,
 id text NOT NULL CHECK(id ~ '^[a-f0-9]{32}$'),
 source_node_run_id text NOT NULL,
 context_sha256 text NOT NULL CHECK(context_sha256 ~ '^[a-f0-9]{64}$'),
 binding jsonb NOT NULL CHECK(jsonb_typeof(binding)='object'),
 status text NOT NULL DEFAULT 'prepared' CHECK(status IN ('prepared','running','completed','held')),
 outputs jsonb,
 error_code text,
 admitted_by text REFERENCES accounts(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 admitted_at timestamptz,
 completed_at timestamptz,
 PRIMARY KEY(owner_id,job_id,id),
 UNIQUE(owner_id,job_id,context_sha256),
 FOREIGN KEY(owner_id,job_id,source_node_run_id) REFERENCES node_runs(owner_id,job_id,id),
 CHECK((status='completed')=(outputs IS NOT NULL)),
 CHECK((status='prepared')=(admitted_at IS NULL))
);
CREATE FUNCTION guard_projection_recoveries() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'projection recovery evidence cannot be deleted'; END IF;
 IF (to_jsonb(NEW)-ARRAY['status','outputs','error_code','admitted_by','admitted_at','completed_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','outputs','error_code','admitted_by','admitted_at','completed_at']) OR
    NOT ((OLD.status='prepared' AND NEW.status='running') OR (OLD.status='running' AND NEW.status IN ('completed','held'))) OR
    (OLD.admitted_at IS NOT NULL AND (NEW.admitted_at IS DISTINCT FROM OLD.admitted_at OR NEW.admitted_by IS DISTINCT FROM OLD.admitted_by)) THEN
  RAISE EXCEPTION 'projection recovery identity/context/outcome is immutable';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER projection_recovery_guard BEFORE UPDATE OR DELETE ON projection_recoveries FOR EACH ROW EXECUTE FUNCTION guard_projection_recoveries();
