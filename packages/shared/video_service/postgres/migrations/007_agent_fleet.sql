-- Explicit opt-in fleet metadata. No consumer, process, credential or deployment startup.
CREATE TABLE agent_configurations (
 agent_id text PRIMARY KEY CHECK(agent_id ~ '^[a-z][a-z0-9_]{0,63}$'),
 revision integer NOT NULL CHECK(revision > 0),
 enabled boolean NOT NULL,
 replicas integer NOT NULL CHECK(replicas BETWEEN 0 AND 8),
 updated_by text NOT NULL REFERENCES accounts(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK((enabled AND replicas > 0) OR (NOT enabled AND replicas = 0))
);
CREATE TABLE agent_instances (
 id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
 agent_id text NOT NULL,
 controller_id text NOT NULL,
 runtime text NOT NULL CHECK(runtime='cpu_subprocess'),
 state text NOT NULL CHECK(state IN ('starting','ready','draining','stopped','failed')),
 in_flight integer NOT NULL DEFAULT 0 CHECK(in_flight BETWEEN 0 AND 1),
 completed bigint NOT NULL DEFAULT 0,
 pid integer,
 error_code text,
 last_assigned_at timestamptz,
 observed_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_instances_routing ON agent_instances(agent_id,state,in_flight,last_assigned_at);
CREATE TABLE agent_configuration_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 agent_id text NOT NULL, revision integer NOT NULL,
 enabled boolean NOT NULL, replicas integer NOT NULL,
 actor_id text NOT NULL REFERENCES accounts(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(agent_id,revision)
);
ALTER TABLE node_runs ADD COLUMN agent_instance_id text REFERENCES agent_instances(id);
-- Administrative workflow definitions are reusable by jobs without transferring asset ownership.
ALTER TABLE jobs ADD COLUMN workflow_owner_id text REFERENCES accounts(id);
UPDATE jobs SET workflow_owner_id=owner_id;
ALTER TABLE jobs ALTER COLUMN workflow_owner_id SET NOT NULL;
ALTER TABLE jobs DROP CONSTRAINT jobs_owner_id_workflow_id_workflow_revision_fkey;
ALTER TABLE jobs ADD CONSTRAINT jobs_workflow_source_fkey
 FOREIGN KEY(workflow_owner_id,workflow_id,workflow_revision)
 REFERENCES workflow_revisions(owner_id,workflow_id,revision);
CREATE FUNCTION reject_workflow_source_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.workflow_owner_id IS DISTINCT FROM OLD.workflow_owner_id THEN
  RAISE EXCEPTION 'Workflow source is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER job_workflow_source_immutable BEFORE UPDATE ON jobs
 FOR EACH ROW EXECUTE FUNCTION reject_workflow_source_mutation();
