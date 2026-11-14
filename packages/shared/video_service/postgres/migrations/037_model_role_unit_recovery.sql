-- Application-owned append-only recovery; no worker grants or root task mutations.
CREATE TABLE model_role_unit_recoveries (
 id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
 owner_id text NOT NULL, job_id text NOT NULL, run_id text NOT NULL,
 task_id text NOT NULL REFERENCES model_role_tasks(task_id),
 revision integer NOT NULL CHECK(revision>0), request_id text NOT NULL,
 request_sha256 text NOT NULL, context_sha256 text NOT NULL,
 context jsonb NOT NULL, manifest jsonb NOT NULL, decisions jsonb NOT NULL,
 reused_attempts jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(reused_attempts)='array'),
 preview_sha256 text NOT NULL, approve_calls boolean NOT NULL,
 additional_call_limit integer NOT NULL CHECK(additional_call_limit BETWEEN 0 AND 10000),
 CHECK(additional_call_limit=0 OR approve_calls),
 status text NOT NULL DEFAULT 'approved' CHECK(status IN ('approved','applied')),
 receipt_sha256 text, prepared jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,job_id,run_id,revision), UNIQUE(owner_id,job_id,run_id,request_id),
 FOREIGN KEY(owner_id,job_id,run_id) REFERENCES node_runs(owner_id,job_id,id),
 CHECK((status='applied')=(receipt_sha256 IS NOT NULL)),
 CHECK(status<>'applied' OR prepared IS NOT NULL)
);
CREATE TABLE model_role_unit_attempts (
 id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
 recovery_id text NOT NULL REFERENCES model_role_unit_recoveries(id),
 unit_index integer NOT NULL CHECK(unit_index>=0), candidate_index integer NOT NULL CHECK(candidate_index>=0),
 input_sha256 text NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','completed','failed','unknown')),
 response jsonb, error_code text, terminal_sha256 text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(recovery_id,unit_index),
 CHECK((status IN ('completed','failed','unknown'))=(terminal_sha256 IS NOT NULL)),
 CHECK(status='completed' OR response IS NULL)
);
CREATE FUNCTION admit_unit_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE recovery model_role_unit_recoveries%ROWTYPE;
BEGIN
 SELECT * INTO recovery FROM model_role_unit_recoveries WHERE id=NEW.recovery_id FOR UPDATE;
 IF NOT FOUND OR recovery.status<>'approved' OR NOT recovery.approve_calls
 OR NEW.status<>'pending' OR recovery.prepared IS NOT NULL
 OR EXISTS (SELECT 1 FROM model_role_unit_recoveries r WHERE r.owner_id=recovery.owner_id
            AND r.job_id=recovery.job_id AND r.run_id=recovery.run_id AND r.revision>recovery.revision)
 OR EXISTS (SELECT 1 FROM jsonb_array_elements(recovery.reused_attempts) p
            WHERE (p->>'unit_index')::integer=NEW.unit_index)
 OR (SELECT count(*) FROM model_role_unit_attempts WHERE recovery_id=NEW.recovery_id)>=recovery.additional_call_limit
 OR NEW.input_sha256 IS DISTINCT FROM (recovery.manifest->'units'->NEW.unit_index->>'input_sha256')
 OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(recovery.decisions) d
                WHERE d->>'action'='retry' AND (d->>'unit_index')::integer=NEW.unit_index
                AND (d->>'candidate_index')::integer=NEW.candidate_index) THEN
 RAISE EXCEPTION 'Recovery attempt not approved' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER unit_attempt_admission BEFORE INSERT ON model_role_unit_attempts FOR EACH ROW EXECUTE FUNCTION admit_unit_attempt();
CREATE FUNCTION admit_unit_recovery() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous model_role_unit_recoveries%ROWTYPE;
 origin model_role_unit_recoveries%ROWTYPE;
 attempt model_role_unit_attempts%ROWTYPE;
 proof jsonb;
BEGIN
 -- Serialize approvals and pending->sending on the same durable Root scope.
 PERFORM 1 FROM node_runs WHERE owner_id=NEW.owner_id AND job_id=NEW.job_id AND id=NEW.run_id FOR UPDATE;
 SELECT * INTO previous FROM model_role_unit_recoveries WHERE owner_id=NEW.owner_id
  AND job_id=NEW.job_id AND run_id=NEW.run_id ORDER BY revision DESC LIMIT 1 FOR UPDATE;
 IF NEW.revision<>coalesce(previous.revision,0)+1 OR previous.status='applied'
 OR NEW.additional_call_limit<>(SELECT count(*) FROM jsonb_array_elements(NEW.decisions) d WHERE d->>'action'='retry')
 OR EXISTS (SELECT 1 FROM model_role_unit_attempts a JOIN model_role_unit_recoveries r ON r.id=a.recovery_id
            WHERE r.owner_id=NEW.owner_id AND r.job_id=NEW.job_id AND r.run_id=NEW.run_id AND a.status IN ('sending','unknown'))
 OR (SELECT count(*) FROM jsonb_array_elements(NEW.reused_attempts))<>
    (SELECT count(DISTINCT p->>'unit_index') FROM jsonb_array_elements(NEW.reused_attempts) p)
 OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.reused_attempts) p, jsonb_array_elements(NEW.decisions) d
            WHERE p->>'unit_index'=d->>'unit_index') THEN
 RAISE EXCEPTION 'Recovery approval scope changed' USING ERRCODE='23514'; END IF;
 FOR proof IN SELECT value FROM jsonb_array_elements(NEW.reused_attempts) LOOP
  SELECT * INTO attempt FROM model_role_unit_attempts WHERE id=proof->>'attempt_id';
  SELECT * INTO origin FROM model_role_unit_recoveries WHERE id=proof->>'recovery_id';
  IF attempt.id IS NULL OR origin.id IS NULL OR attempt.recovery_id IS DISTINCT FROM origin.id
  OR origin.revision>=NEW.revision OR origin.owner_id IS DISTINCT FROM NEW.owner_id
  OR origin.job_id IS DISTINCT FROM NEW.job_id OR origin.run_id IS DISTINCT FROM NEW.run_id
  OR origin.task_id IS DISTINCT FROM NEW.task_id OR origin.context_sha256 IS DISTINCT FROM NEW.context_sha256
  OR origin.context IS DISTINCT FROM NEW.context OR origin.manifest IS DISTINCT FROM NEW.manifest
  OR NOT origin.approve_calls OR origin.additional_call_limit<=0
  OR attempt.status<>'completed' OR attempt.response IS NULL
  OR attempt.terminal_sha256 IS DISTINCT FROM (proof->>'terminal_sha256')
  OR attempt.unit_index IS DISTINCT FROM (proof->>'unit_index')::integer
  OR attempt.candidate_index IS DISTINCT FROM (proof->>'candidate_index')::integer
  OR attempt.input_sha256 IS DISTINCT FROM (proof->>'input_sha256')
  OR attempt.input_sha256 IS DISTINCT FROM (NEW.manifest->'units'->attempt.unit_index->>'input_sha256')
  OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(origin.decisions) d WHERE d->>'action'='retry'
                 AND (d->>'unit_index')::integer=attempt.unit_index AND (d->>'candidate_index')::integer=attempt.candidate_index)
  THEN RAISE EXCEPTION 'Invalid retained recovery attempt' USING ERRCODE='23514'; END IF;
 END LOOP;
 -- In an unchanged context every newly completed or already carried success
 -- must survive the next approval, including when another unit still failed.
 IF previous.context_sha256=NEW.context_sha256 AND previous.context=NEW.context AND previous.manifest=NEW.manifest
 AND EXISTS (SELECT 1 FROM (
   SELECT id FROM model_role_unit_attempts WHERE recovery_id=previous.id AND status='completed'
   UNION SELECT p->>'attempt_id' FROM jsonb_array_elements(previous.reused_attempts) p
  ) retained WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.reused_attempts) p WHERE p->>'attempt_id'=retained.id))
 THEN RAISE EXCEPTION 'Retained recovery success omitted' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER unit_recovery_admission BEFORE INSERT ON model_role_unit_recoveries FOR EACH ROW EXECUTE FUNCTION admit_unit_recovery();
CREATE FUNCTION protect_unit_recovery() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (to_jsonb(NEW)-'status'-'receipt_sha256'-'prepared') IS DISTINCT FROM (to_jsonb(OLD)-'status'-'receipt_sha256'-'prepared')
 OR (OLD.prepared IS NOT NULL AND NEW.prepared IS DISTINCT FROM OLD.prepared)
 OR (OLD.status='applied' AND NEW IS DISTINCT FROM OLD)
 OR (NEW.status<>OLD.status AND NOT (OLD.status='approved' AND NEW.status='applied')) THEN
 RAISE EXCEPTION 'Immutable unit recovery' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER unit_recovery_immutable BEFORE UPDATE ON model_role_unit_recoveries FOR EACH ROW EXECUTE FUNCTION protect_unit_recovery();
CREATE TRIGGER unit_recovery_no_delete BEFORE DELETE ON model_role_unit_recoveries FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE FUNCTION protect_unit_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE recovery model_role_unit_recoveries%ROWTYPE;
BEGIN
 IF OLD.status='pending' AND NEW.status='sending' THEN
  SELECT * INTO recovery FROM model_role_unit_recoveries WHERE id=OLD.recovery_id;
  PERFORM 1 FROM node_runs WHERE owner_id=recovery.owner_id AND job_id=recovery.job_id AND id=recovery.run_id FOR UPDATE;
  IF recovery.status<>'approved' OR recovery.prepared IS NOT NULL
  OR EXISTS (SELECT 1 FROM model_role_unit_recoveries r WHERE r.owner_id=recovery.owner_id
             AND r.job_id=recovery.job_id AND r.run_id=recovery.run_id AND r.revision>recovery.revision)
  OR EXISTS (SELECT 1 FROM jsonb_array_elements(recovery.reused_attempts) p WHERE (p->>'unit_index')::integer=NEW.unit_index)
  THEN RAISE EXCEPTION 'Recovery attempt superseded' USING ERRCODE='23514'; END IF;
 END IF;
 IF (to_jsonb(NEW)-'status'-'response'-'error_code'-'terminal_sha256') IS DISTINCT FROM (to_jsonb(OLD)-'status'-'response'-'error_code'-'terminal_sha256')
 OR (OLD.status IN ('completed','failed','unknown') AND NEW IS DISTINCT FROM OLD)
 OR (NEW.status<>OLD.status AND NOT ((OLD.status='pending' AND NEW.status='sending') OR (OLD.status='sending' AND NEW.status IN ('completed','failed','unknown')))) THEN
 RAISE EXCEPTION 'Immutable recovery attempt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER unit_attempt_immutable BEFORE UPDATE ON model_role_unit_attempts FOR EACH ROW EXECUTE FUNCTION protect_unit_attempt();
CREATE TRIGGER unit_attempt_no_delete BEFORE DELETE ON model_role_unit_attempts FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
