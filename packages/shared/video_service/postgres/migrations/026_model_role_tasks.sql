-- Application orchestrator only. Model roles receive no access to these tables.
CREATE TABLE model_role_tasks (
 owner_id text NOT NULL,job_id text NOT NULL,attempt_id text NOT NULL,
 task_id text NOT NULL UNIQUE CHECK(task_id ~ '^[a-f0-9]{32}$'),
 generation integer NOT NULL,request_sha256 text NOT NULL,
 envelope jsonb NOT NULL,envelope_sha256 text NOT NULL,
 frozen_candidates jsonb NOT NULL,
 phase text NOT NULL DEFAULT 'ready' CHECK(phase IN ('ready','sending','sent','unknown','held','adopting','accepted','cancelled')),
 result_message jsonb,result_sha256 text,adoption_result jsonb,
 held_reason text,used_calls integer,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,job_id,attempt_id),
 FOREIGN KEY(owner_id,job_id,attempt_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE FUNCTION protect_model_role_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.owner_id,NEW.job_id,NEW.attempt_id,NEW.task_id,NEW.generation,NEW.request_sha256,NEW.envelope,NEW.envelope_sha256,NEW.frozen_candidates)
 IS DISTINCT FROM ROW(OLD.owner_id,OLD.job_id,OLD.attempt_id,OLD.task_id,OLD.generation,OLD.request_sha256,OLD.envelope,OLD.envelope_sha256,OLD.frozen_candidates)
 OR (OLD.result_sha256 IS NOT NULL AND NEW.result_sha256 IS DISTINCT FROM OLD.result_sha256)
 OR (OLD.adoption_result IS NOT NULL AND NEW.adoption_result IS DISTINCT FROM OLD.adoption_result) THEN
 RAISE EXCEPTION 'Role task binding/result is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER model_role_binding_immutable BEFORE UPDATE ON model_role_tasks FOR EACH ROW EXECUTE FUNCTION protect_model_role_binding();
CREATE TRIGGER model_role_no_delete BEFORE DELETE ON model_role_tasks FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();

CREATE TABLE model_role_tool_calls (
 task_id text NOT NULL REFERENCES model_role_tasks(task_id),chunk_index integer NOT NULL CHECK(chunk_index>=0),
 input_sha256 text NOT NULL,model jsonb NOT NULL,status text NOT NULL CHECK(status IN ('started','completed','failed','unknown')),
 response jsonb,error_code text,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(task_id,chunk_index)
);
CREATE TRIGGER model_role_tool_no_delete BEFORE DELETE ON model_role_tool_calls FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
