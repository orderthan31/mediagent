-- Optional durable lifecycle journal. Only the fixed host executor writes it.
CREATE TABLE remote_control_batches (
    request_id text PRIMARY KEY REFERENCES remote_control_requests(request_id),
    agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
    contract_sha256 text NOT NULL CHECK(contract_sha256 ~ '^[a-f0-9]{64}$'),
    prepared_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE remote_control_actions (
    id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
    request_id text NOT NULL REFERENCES remote_control_batches(request_id),
    worker_id text NOT NULL CHECK(worker_id ~ '^[a-f0-9]{32}$'),
    action text NOT NULL CHECK(action IN ('start','stop')),
    phase text NOT NULL DEFAULT 'planned' CHECK(phase IN ('planned','issuing','sent','confirmed','unknown')),
    issue_count integer NOT NULL DEFAULT 0 CHECK(issue_count BETWEEN 0 AND 1),
    before_boot_id text,
    issued_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(request_id,worker_id),
    CHECK((phase='planned' AND issue_count=0) OR (phase<>'planned' AND issue_count=1))
);
