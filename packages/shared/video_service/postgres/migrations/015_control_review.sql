-- Administrator decisions are intents; only the fixed host writes outcomes.
ALTER TABLE remote_control_groups ADD COLUMN observation_revision bigint NOT NULL DEFAULT 0;
ALTER TABLE remote_control_groups ADD COLUMN observation_sha256 text;
ALTER TABLE remote_control_groups ADD COLUMN quarantined boolean NOT NULL DEFAULT false;
ALTER TABLE remote_control_requests DROP CONSTRAINT remote_control_requests_phase_check;
ALTER TABLE remote_control_requests ADD CONSTRAINT remote_control_requests_phase_check CHECK(phase IN ('queued','applying','succeeded','unknown','reviewed_completed','reviewed_failed'));
CREATE TABLE remote_control_ack_evidence (
    action_id text PRIMARY KEY REFERENCES remote_control_actions(id),
    receipt_sha256 text,
    facts jsonb,
    valid boolean NOT NULL,
    error_code text,
    verified_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE remote_control_review_heads (
    agent_id text PRIMARY KEY REFERENCES remote_control_groups(agent_id),
    revision bigint NOT NULL DEFAULT 0,
    pending_decision text,
    last_decision text
);
CREATE TABLE remote_control_review_plans (
    id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
    agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
    request_id text NOT NULL REFERENCES remote_control_requests(request_id),
    actor_id text NOT NULL REFERENCES accounts(id),
    context_sha256 text NOT NULL,
    context jsonb NOT NULL,
    allowed jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '2 minutes'
);
CREATE TABLE remote_control_review_decisions (
    id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),
    agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
    request_id text NOT NULL REFERENCES remote_control_requests(request_id),
    actor_id text NOT NULL REFERENCES accounts(id),
    plan_id text NOT NULL REFERENCES remote_control_review_plans(id),
    choice text NOT NULL CHECK(choice IN ('hold','confirm_observed','quarantine_failed')),
    reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    payload_sha256 text NOT NULL,
    review_revision bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(agent_id,review_revision)
);
CREATE TABLE remote_control_review_results (
    decision_id text PRIMARY KEY REFERENCES remote_control_review_decisions(id),
    outcome text NOT NULL CHECK(outcome IN ('held','observed_completed','failed_quarantined','rejected_stale')),
    evidence jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION immutable_control_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable_control_review_record'; END $$;
CREATE TRIGGER immutable_control_review_plans BEFORE UPDATE OR DELETE ON remote_control_review_plans FOR EACH ROW EXECUTE FUNCTION immutable_control_review();
CREATE TRIGGER immutable_control_review_decisions BEFORE UPDATE OR DELETE ON remote_control_review_decisions FOR EACH ROW EXECUTE FUNCTION immutable_control_review();
CREATE TRIGGER immutable_control_review_results BEFORE UPDATE OR DELETE ON remote_control_review_results FOR EACH ROW EXECUTE FUNCTION immutable_control_review();
