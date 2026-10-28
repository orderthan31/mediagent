CREATE TABLE agent_pool_roles (
 role text PRIMARY KEY, max_instances integer NOT NULL CHECK(max_instances BETWEEN 1 AND 16),
 memory_bytes bigint NOT NULL CHECK(memory_bytes>0), idle_seconds integer NOT NULL CHECK(idle_seconds>0),
 template_sha256 text NOT NULL CHECK(length(template_sha256)=64), enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE agent_pool_jobs (
 owner_id text NOT NULL, job_id text NOT NULL, generation integer NOT NULL, claim_id text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(owner_id,job_id,generation)
);
CREATE TABLE agent_pool_demands (
 owner_id text NOT NULL, job_id text NOT NULL, generation integer NOT NULL, node_id text NOT NULL,
 role text NOT NULL REFERENCES agent_pool_roles(role), node_run_id text,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(owner_id,job_id,generation,node_id)
);
CREATE TABLE agent_pool_instances (
 id text PRIMARY KEY, role text NOT NULL REFERENCES agent_pool_roles(role), slot integer NOT NULL,
 template_sha256 text NOT NULL, phase text NOT NULL CHECK(phase IN('creating','starting','ready','busy','draining','stopping','removed','held')),
 container_id text, boot_id text, observed_at timestamptz, ready_at double precision,
 last_completed_at double precision, unsettled integer NOT NULL DEFAULT 0,
 start_issued_at timestamptz, stop_issued_at timestamptz, error_code text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX agent_pool_live_slot ON agent_pool_instances(role,slot) WHERE phase<>'removed';
CREATE TABLE agent_pool_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, instance_id text NOT NULL,
 role text NOT NULL, event text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE VIEW agent_pool_capacity AS
 SELECT d.role,count(*) FILTER(WHERE d.node_run_id IS NULL) AS queued,
 count(*) FILTER(WHERE d.node_run_id IS NOT NULL AND r.status IN('waiting','running')AND(r.status='waiting'OR r.lease_expires_at>now())) AS inflight
 FROM agent_pool_demands d JOIN jobs j ON j.owner_id=d.owner_id AND j.id=d.job_id AND j.generation=d.generation
 LEFT JOIN node_runs r ON r.id=d.node_run_id
 WHERE j.status IN('waiting','running')AND NOT j.cancel_requested AND j.active_claim_id IS NOT NULL
 GROUP BY d.role;
