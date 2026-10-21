-- Opt-in durable admission only. No target discovery or Docker authority in API.
CREATE TABLE remote_control_groups (
    agent_id text PRIMARY KEY CHECK (agent_id ~ '^[a-z][a-z0-9_.-]{0,63}$'),
    contract_sha256 text NOT NULL CHECK (contract_sha256 ~ '^[a-f0-9]{64}$'),
    slot_ids jsonb NOT NULL CHECK (jsonb_typeof(slot_ids)='array'),
    capacity integer NOT NULL CHECK (capacity BETWEEN 1 AND 8),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision>=0),
    enabled boolean NOT NULL DEFAULT false,
    replicas integer NOT NULL DEFAULT 0,
    pending_request text,
    observed jsonb,
    observed_at timestamptz,
    CHECK (replicas BETWEEN 0 AND capacity),
    CHECK (enabled=(replicas>0))
);
CREATE TABLE remote_control_requests (
    request_id text PRIMARY KEY CHECK (request_id ~ '^[a-f0-9]{32}$'),
    agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
    actor_id text NOT NULL REFERENCES accounts(id),
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    revision bigint NOT NULL,
    replicas integer NOT NULL CHECK (replicas BETWEEN 0 AND 8),
    phase text NOT NULL CHECK (phase IN ('queued','applying','succeeded','unknown')),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(agent_id,revision)
);
CREATE TABLE remote_control_reports (
    worker_id text PRIMARY KEY CHECK (worker_id ~ '^[a-f0-9]{32}$'),
    agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
    boot_id text NOT NULL CHECK (boot_id ~ '^[a-f0-9]{32}$'),
    state text NOT NULL CHECK (state IN ('connected','ready','busy','stopping','stopped')),
    ticket_id text,
    ticket_number bigint,
    received_at timestamptz NOT NULL DEFAULT now()
);
