-- Separate processing observations; never rewrites an old job/claim/outbox.
CREATE TABLE job_processing_cases (
 id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
 owner_id text NOT NULL, job_id text NOT NULL, node_run_id text NOT NULL,
 cause text NOT NULL CHECK(cause IN ('legacy_lease_expired','dispatch_unknown')),
 state text NOT NULL DEFAULT 'needs_review' CHECK(state IN ('needs_review','held','child_created')),
 revision integer NOT NULL DEFAULT 1,
 evidence_sha256 text NOT NULL,
 child_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,job_id),
 FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id),
 FOREIGN KEY(owner_id,child_id) REFERENCES jobs(owner_id,id)
);
CREATE TABLE job_processing_observations (
 case_id text NOT NULL REFERENCES job_processing_cases(id), revision integer NOT NULL,
 evidence_sha256 text NOT NULL, evidence jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(case_id,revision)
);
CREATE TRIGGER job_processing_observation_immutable BEFORE UPDATE OR DELETE ON job_processing_observations
 FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TABLE job_processing_plans (
 id text PRIMARY KEY, case_id text NOT NULL REFERENCES job_processing_cases(id),
 actor_id text NOT NULL REFERENCES accounts(id), revision integer NOT NULL,
 evidence_sha256 text NOT NULL, context jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE job_processing_decisions (
 id text PRIMARY KEY, case_id text NOT NULL REFERENCES job_processing_cases(id),
 plan_id text NOT NULL REFERENCES job_processing_plans(id), actor_id text NOT NULL REFERENCES accounts(id),
 choice text NOT NULL CHECK(choice IN ('hold','create_child')),
 reason text NOT NULL CHECK(length(trim(reason))>0 AND length(reason)<=1000),
 request_sha256 text NOT NULL, evidence_sha256 text NOT NULL,
 acknowledge_duplicate_risk boolean NOT NULL,
 authority_snapshot jsonb NOT NULL,
 CHECK(choice<>'create_child' OR acknowledge_duplicate_risk),
 owner_id text NOT NULL, child_id text, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,child_id) REFERENCES jobs(owner_id,id)
);
CREATE TRIGGER job_processing_plan_immutable BEFORE UPDATE OR DELETE ON job_processing_plans
 FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TRIGGER job_processing_decision_immutable BEFORE UPDATE OR DELETE ON job_processing_decisions
 FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TABLE job_processing_late_results (
 case_id text NOT NULL REFERENCES job_processing_cases(id), message_sha256 text NOT NULL,
 result jsonb NOT NULL, verified boolean NOT NULL, outputs jsonb NOT NULL,
 error_code text, received_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(case_id,message_sha256)
);
CREATE TRIGGER job_processing_late_result_immutable BEFORE UPDATE OR DELETE ON job_processing_late_results
 FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
ALTER TABLE broker_dispatch_queue ADD COLUMN release_decision_id text REFERENCES job_processing_decisions(id);
DROP INDEX broker_dispatch_one_inflight_per_group;
CREATE UNIQUE INDEX broker_dispatch_one_inflight_per_group ON broker_dispatch_queue(agent_id)
 WHERE phase IN ('sending','sent','received','unknown') AND release_decision_id IS NULL;
CREATE FUNCTION preserve_dispatch_release() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.release_decision_id IS NOT NULL AND NEW.release_decision_id IS DISTINCT FROM OLD.release_decision_id THEN
  RAISE EXCEPTION 'Reviewed release is immutable';
 END IF;
 IF NEW.release_decision_id IS DISTINCT FROM OLD.release_decision_id AND NOT EXISTS(
  SELECT 1 FROM job_processing_decisions d JOIN job_processing_cases c ON c.id=d.case_id
  WHERE d.id=NEW.release_decision_id AND d.choice='create_child' AND d.child_id IS NOT NULL
   AND c.child_id=d.child_id AND c.owner_id=OLD.owner_id AND c.job_id=OLD.job_id AND c.node_run_id=OLD.node_run_id
 ) THEN RAISE EXCEPTION 'Release requires its own audited child decision'; END IF;
 IF EXISTS(SELECT 1 FROM job_processing_cases WHERE owner_id=OLD.owner_id AND job_id=OLD.job_id)
 AND (to_jsonb(NEW)-'release_decision_id') IS DISTINCT FROM (to_jsonb(OLD)-'release_decision_id') THEN
  RAISE EXCEPTION 'Original dispatch evidence is immutable during review';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER preserve_dispatch_release BEFORE UPDATE ON broker_dispatch_queue
 FOR EACH ROW EXECUTE FUNCTION preserve_dispatch_release();
CREATE FUNCTION preserve_processing_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_job text;
BEGIN
 IF TG_TABLE_NAME='jobs' THEN source_job:=OLD.id;
 ELSIF TG_TABLE_NAME='message_outbox' THEN source_job:=OLD.aggregate_id;
 ELSE source_job:=OLD.job_id; END IF;
 IF EXISTS(SELECT 1 FROM job_processing_cases WHERE owner_id=OLD.owner_id AND job_id=source_job) THEN
  RAISE EXCEPTION 'Processing review preserves original facts' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER preserve_processing_job BEFORE UPDATE OR DELETE ON jobs FOR EACH ROW EXECUTE FUNCTION preserve_processing_source();
CREATE TRIGGER preserve_processing_run BEFORE UPDATE OR DELETE ON node_runs FOR EACH ROW EXECUTE FUNCTION preserve_processing_source();
CREATE TRIGGER preserve_processing_outbox BEFORE UPDATE OR DELETE ON message_outbox FOR EACH ROW EXECUTE FUNCTION preserve_processing_source();
