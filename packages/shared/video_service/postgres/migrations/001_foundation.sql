-- Renewal PostgreSQL foundation. Explicit migration only; never imports legacy data.
CREATE TABLE accounts (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    username text NOT NULL CHECK (username ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$'),
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin','user')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX accounts_username_ci ON accounts (lower(username));
CREATE TABLE sessions (
    token_hash text PRIMARY KEY CHECK (token_hash ~ '^[a-f0-9]{64}$'),
    account_id text NOT NULL REFERENCES accounts(id),
    csrf_hash text NOT NULL CHECK (csrf_hash ~ '^[a-f0-9]{64}$'),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_account ON sessions(account_id);
CREATE TABLE login_limits (
    bucket text PRIMARY KEY,
    attempts integer NOT NULL CHECK (attempts > 0),
    expires_at timestamptz NOT NULL
);
CREATE TABLE serving_connections (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    revision integer NOT NULL CHECK (revision >= 0),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY(owner_id,id)
);
CREATE TABLE connection_revisions (
    owner_id text NOT NULL,
    connection_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    provider text NOT NULL CHECK (length(provider) BETWEEN 1 AND 80),
    protocol text NOT NULL CHECK (protocol IN ('openai_compatible','openai','anthropic','gemini')),
    endpoint text NOT NULL CHECK (length(endpoint) BETWEEN 1 AND 2048),
    credential_ref text CHECK (credential_ref ~ '^env:[A-Z][A-Z0-9_]{0,99}$'),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,connection_id,revision),
    FOREIGN KEY(owner_id,connection_id) REFERENCES serving_connections(owner_id,id)
);
CREATE TABLE registered_models (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    revision integer NOT NULL CHECK (revision >= 0),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY(owner_id,id)
);
CREATE TABLE model_revisions (
    owner_id text NOT NULL,
    model_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    remote_model text NOT NULL CHECK (length(remote_model) BETWEEN 1 AND 200),
    connection_id text NOT NULL,
    connection_revision integer NOT NULL,
    capabilities text[] NOT NULL CHECK (cardinality(capabilities) > 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,model_id,revision),
    FOREIGN KEY(owner_id,model_id) REFERENCES registered_models(owner_id,id),
    FOREIGN KEY(owner_id,connection_id,connection_revision)
        REFERENCES connection_revisions(owner_id,connection_id,revision)
);
CREATE TABLE assets (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    filename text NOT NULL,
    storage_key text NOT NULL,
    bytes bigint NOT NULL CHECK (bytes >= 0),
    sha256 text CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,id)
);
CREATE TABLE workflows (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    revision integer NOT NULL CHECK (revision >= 0),
    PRIMARY KEY(owner_id,id)
);
CREATE TABLE workflow_revisions (
    owner_id text NOT NULL,
    workflow_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    name text NOT NULL,
    definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,workflow_id,revision),
    FOREIGN KEY(owner_id,workflow_id) REFERENCES workflows(owner_id,id)
);
CREATE TABLE jobs (
    owner_id text NOT NULL REFERENCES accounts(id),
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    ticket_number bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    asset_id text NOT NULL,
    workflow_id text NOT NULL,
    workflow_revision integer NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','waiting','running','review_required','completed','failed','cancelled')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[a-f0-9]{64}$'),
    parent_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,id),
    FOREIGN KEY(owner_id,asset_id) REFERENCES assets(owner_id,id),
    FOREIGN KEY(owner_id,workflow_id,workflow_revision) REFERENCES workflow_revisions(owner_id,workflow_id,revision),
    FOREIGN KEY(owner_id,parent_id) REFERENCES jobs(owner_id,id)
);
CREATE INDEX jobs_owner_created ON jobs(owner_id,created_at DESC,id);
CREATE TABLE node_runs (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    node_id text NOT NULL,
    agent_revision text NOT NULL,
    iteration integer NOT NULL DEFAULT 0 CHECK (iteration >= 0),
    attempt integer NOT NULL CHECK (attempt > 0),
    generation integer NOT NULL CHECK (generation > 0),
    status text NOT NULL CHECK (status IN ('waiting','running','review_required','completed','failed','cancelled','quarantined')),
    input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[a-f0-9]{64}$'),
    settings_sha256 text NOT NULL CHECK (settings_sha256 ~ '^[a-f0-9]{64}$'),
    result jsonb,
    error_code text,
    lease_owner text,
    lease_expires_at timestamptz,
    PRIMARY KEY(owner_id,job_id,id),
    UNIQUE(owner_id,job_id,node_id,iteration,attempt,generation),
    FOREIGN KEY(owner_id,job_id) REFERENCES jobs(owner_id,id)
);
CREATE TABLE artifacts (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    node_run_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    type text NOT NULL,
    storage_key text NOT NULL,
    bytes bigint NOT NULL CHECK (bytes >= 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    PRIMARY KEY(owner_id,id),
    FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE TABLE review_tasks (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    node_run_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    revision integer NOT NULL CHECK (revision > 0),
    contract jsonb NOT NULL CHECK (jsonb_typeof(contract) = 'object'),
    draft jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','changes_requested','confirmed')),
    confirmed_sha256 text CHECK (confirmed_sha256 ~ '^[a-f0-9]{64}$'),
    PRIMARY KEY(owner_id,id),
    FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE TABLE execution_consents (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    request_id text NOT NULL,
    plan_sha256 text NOT NULL CHECK (plan_sha256 ~ '^[a-f0-9]{64}$'),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,job_id,id),
    UNIQUE(owner_id,job_id,request_id),
    FOREIGN KEY(owner_id,job_id) REFERENCES jobs(owner_id,id)
);
CREATE TABLE execution_claims (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    consent_id text NOT NULL,
    generation integer NOT NULL CHECK (generation > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,job_id,id),
    UNIQUE(owner_id,job_id,consent_id),
    FOREIGN KEY(owner_id,job_id,consent_id) REFERENCES execution_consents(owner_id,job_id,id)
);
CREATE TABLE external_requests (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    claim_id text NOT NULL,
    id text NOT NULL CHECK (id ~ '^[0-9a-f]{32}$'),
    logical_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[a-f0-9]{64}$'),
    status text NOT NULL CHECK (status IN ('prepared','in_flight','succeeded','failed','ambiguous')),
    result_sha256 text CHECK (result_sha256 ~ '^[a-f0-9]{64}$'),
    PRIMARY KEY(owner_id,job_id,id),
    UNIQUE(owner_id,job_id,claim_id,logical_key),
    FOREIGN KEY(owner_id,job_id,claim_id) REFERENCES execution_claims(owner_id,job_id,id)
);
