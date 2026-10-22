-- Application-owned durable waiting, independent of broker command TTL.
-- Enrollment is new-attempt-only. Existing jobs/outbox/claims are not rewritten.
CREATE TABLE broker_dispatch_queue (
 owner_id text NOT NULL,
 job_id text NOT NULL,
 node_run_id text PRIMARY KEY,
 agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
 phase text NOT NULL DEFAULT 'pending' CHECK(phase IN
 ('pending','sending','sent','received','completed','cancelled','unknown')),
 worker_id text,
 boot_id text,
 published_at timestamptz,
 received_at timestamptz,
 error_code text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE INDEX broker_dispatch_pending ON broker_dispatch_queue(agent_id,created_at,node_run_id)
 WHERE phase='pending';
CREATE UNIQUE INDEX broker_dispatch_one_inflight_per_group ON broker_dispatch_queue(agent_id)
 WHERE phase IN ('sending','sent','received','unknown');
