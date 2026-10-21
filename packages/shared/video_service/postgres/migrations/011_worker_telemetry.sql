-- Additive status-only observations. No job/result/credential changes.
CREATE TABLE worker_observations (
    worker_id text PRIMARY KEY CHECK (worker_id ~ '^[a-f0-9]{32}$'),
    family text NOT NULL CHECK (family IN ('cpu','model','gpu')),
    role text NOT NULL,
    boot_id text NOT NULL CHECK (boot_id ~ '^[a-f0-9]{32}$'),
    sequence bigint NOT NULL CHECK (sequence >= 0),
    state text NOT NULL CHECK (state IN ('connected','ready','busy','stopping','stopped')),
    ticket_id text,
    attempt_id text,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX worker_observations_role ON worker_observations(role);
CREATE TABLE worker_observation_events (
    worker_id text NOT NULL REFERENCES worker_observations(worker_id),
    boot_id text NOT NULL,
    sequence bigint NOT NULL,
    state text NOT NULL,
    ticket_id text,
    attempt_id text,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(worker_id,boot_id,sequence)
);
CREATE TABLE telemetry_observer (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    received_at timestamptz NOT NULL DEFAULT now()
);
