-- Additive candidate only: durable per-segment intents and bounded model calls.
-- No GRANT, existing-ledger rewrite, preview migration, or automatic worker start.
CREATE TABLE model_call_budgets (
    owner_id text NOT NULL,
    job_id text NOT NULL,
    node_run_id text NOT NULL,
    command_sha256 text NOT NULL CHECK (command_sha256 ~ '^[a-f0-9]{64}$'),
    max_calls integer NOT NULL CHECK (max_calls BETWEEN 1 AND 4096),
    issued_count integer NOT NULL DEFAULT 0 CHECK (issued_count BETWEEN 0 AND max_calls),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,job_id,node_run_id),
    FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES node_runs(owner_id,job_id,id)
);
CREATE TABLE model_chunk_cache (
    owner_id text NOT NULL REFERENCES accounts(id),
    context_sha256 text NOT NULL CHECK (context_sha256 ~ '^[a-f0-9]{64}$'),
    context jsonb NOT NULL CHECK (jsonb_typeof(context)='object'),
    status text NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared','started','completed','held','cancelled')),
    output_ref jsonb,
    selected_pin jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id,context_sha256),
    CHECK ((status='completed')=(output_ref IS NOT NULL AND selected_pin IS NOT NULL))
);
CREATE TABLE model_chunk_attempts (
    owner_id text NOT NULL,
    context_sha256 text NOT NULL,
    candidate_index integer NOT NULL CHECK (candidate_index BETWEEN 0 AND 3),
    call_id text NOT NULL CHECK (call_id ~ '^[a-f0-9]{32}$'),
    job_id text NOT NULL,
    node_run_id text NOT NULL,
    model_id text NOT NULL CHECK (model_id ~ '^[a-f0-9]{32}$'),
    model_revision integer NOT NULL CHECK (model_revision>0),
    connection_id text NOT NULL CHECK (connection_id ~ '^[a-f0-9]{32}$'),
    connection_revision integer NOT NULL CHECK (connection_revision>0),
    pin_sha256 text NOT NULL CHECK (pin_sha256 ~ '^[a-f0-9]{64}$'),
    status text NOT NULL CHECK (status IN ('started','completed','failed','unknown','cancelled')),
    outcome_ref jsonb,
    error_code text,
    intent_at timestamptz NOT NULL DEFAULT now(),
    settled_at timestamptz,
    PRIMARY KEY(owner_id,context_sha256,candidate_index),
    UNIQUE(owner_id,call_id),
    FOREIGN KEY(owner_id,context_sha256) REFERENCES model_chunk_cache(owner_id,context_sha256),
    FOREIGN KEY(owner_id,job_id,node_run_id) REFERENCES model_call_budgets(owner_id,job_id,node_run_id)
);
CREATE FUNCTION guard_model_batch_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'model billing evidence cannot be deleted';
    END IF;
    IF TG_TABLE_NAME='model_call_budgets' THEN
        IF (to_jsonb(NEW)-'issued_count') IS DISTINCT FROM (to_jsonb(OLD)-'issued_count') OR NEW.issued_count<OLD.issued_count THEN
            RAISE EXCEPTION 'model budget context is immutable and spend is monotonic';
        END IF;
    ELSIF TG_TABLE_NAME='model_chunk_cache' THEN
        IF NEW.owner_id<>OLD.owner_id OR NEW.context_sha256<>OLD.context_sha256 OR NEW.context IS DISTINCT FROM OLD.context OR NEW.created_at<>OLD.created_at OR OLD.status IN ('completed','held','cancelled') THEN
            RAISE EXCEPTION 'model chunk identity or terminal outcome is immutable';
        END IF;
    ELSIF TG_TABLE_NAME='model_chunk_attempts' THEN
        IF (to_jsonb(NEW)-ARRAY['status','outcome_ref','error_code','settled_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','outcome_ref','error_code','settled_at']) OR OLD.status<>'started' THEN
            RAISE EXCEPTION 'model call intent and settled outcome are immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER model_call_budget_guard BEFORE UPDATE OR DELETE ON model_call_budgets FOR EACH ROW EXECUTE FUNCTION guard_model_batch_ledger();
CREATE TRIGGER model_chunk_cache_guard BEFORE UPDATE OR DELETE ON model_chunk_cache FOR EACH ROW EXECUTE FUNCTION guard_model_batch_ledger();
CREATE TRIGGER model_chunk_attempt_guard BEFORE UPDATE OR DELETE ON model_chunk_attempts FOR EACH ROW EXECUTE FUNCTION guard_model_batch_ledger();
