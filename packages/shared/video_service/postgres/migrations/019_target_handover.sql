-- Single logical-slot handover. History is append-only; current pointer changes
-- only while a separately admitted transition is applying and leaves count zero.
ALTER TABLE remote_control_groups ADD COLUMN target_epoch bigint NOT NULL DEFAULT 0 CHECK(target_epoch>=0);
ALTER TABLE remote_control_groups ADD COLUMN pending_handover text;
ALTER TABLE remote_control_requests ADD COLUMN target_epoch bigint NOT NULL DEFAULT 0;
CREATE TABLE control_target_contracts (
 agent_id text NOT NULL REFERENCES remote_control_groups(agent_id), epoch bigint NOT NULL,
 contract_sha256 text NOT NULL, descriptor jsonb NOT NULL, transition_id text,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(agent_id,epoch)
);
CREATE TABLE control_target_candidates (
 id text PRIMARY KEY, agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
 from_epoch bigint NOT NULL, from_contract text NOT NULL, old_descriptor jsonb NOT NULL,
 new_descriptor jsonb NOT NULL, new_contract text NOT NULL, native_evidence jsonb NOT NULL, context jsonb NOT NULL,
 context_sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE control_target_plans (
 id text PRIMARY KEY, agent_id text NOT NULL, candidate_id text NOT NULL REFERENCES control_target_candidates(id),
 actor_id text NOT NULL REFERENCES accounts(id), context jsonb NOT NULL, context_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE control_target_transitions (
 id text PRIMARY KEY, agent_id text NOT NULL REFERENCES remote_control_groups(agent_id),
 candidate_id text NOT NULL REFERENCES control_target_candidates(id), plan_id text NOT NULL REFERENCES control_target_plans(id),
 actor_id text NOT NULL REFERENCES accounts(id), authority jsonb NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 1000),
 phase text NOT NULL CHECK(phase IN ('planned','applying','applied','held')),
 error_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE control_target_events (
 sequence bigserial PRIMARY KEY, transition_id text NOT NULL REFERENCES control_target_transitions(id),
 phase text NOT NULL, error_code text, recorded_at timestamptz NOT NULL DEFAULT now(),
 db_actor text NOT NULL DEFAULT session_user, db_session integer NOT NULL DEFAULT pg_backend_pid()
);
CREATE FUNCTION protect_target_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable_target_history' USING ERRCODE='23514'; END $$;
CREATE TRIGGER target_contract_immutable BEFORE UPDATE OR DELETE ON control_target_contracts FOR EACH ROW EXECUTE FUNCTION protect_target_history();
CREATE TRIGGER target_candidate_immutable BEFORE UPDATE OR DELETE ON control_target_candidates FOR EACH ROW EXECUTE FUNCTION protect_target_history();
CREATE TRIGGER target_plan_immutable BEFORE UPDATE OR DELETE ON control_target_plans FOR EACH ROW EXECUTE FUNCTION protect_target_history();
CREATE TRIGGER target_event_immutable BEFORE UPDATE OR DELETE ON control_target_events FOR EACH ROW EXECUTE FUNCTION protect_target_history();
CREATE FUNCTION guard_target_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_target_transition' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' AND (NEW.phase<>'planned' OR NOT EXISTS(SELECT 1 FROM accounts a JOIN control_target_plans p ON p.actor_id=a.id WHERE a.id=NEW.actor_id AND a.active AND a.role='admin' AND p.id=NEW.plan_id AND p.agent_id=NEW.agent_id AND p.candidate_id=NEW.candidate_id AND NEW.authority=jsonb_build_object('id',a.id,'role',a.role,'active',a.active))) THEN RAISE EXCEPTION 'target_transition_requires_authorized_plan' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['phase','error_code','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['phase','error_code','updated_at'])
   OR NOT ((OLD.phase='planned' AND NEW.phase IN ('applying','held')) OR (OLD.phase='applying' AND NEW.phase IN ('applied','held'))) THEN
   RAISE EXCEPTION 'invalid_target_transition' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_transition_guard BEFORE INSERT OR UPDATE OR DELETE ON control_target_transitions FOR EACH ROW EXECUTE FUNCTION guard_target_transition();
CREATE FUNCTION record_target_event() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
BEGIN INSERT INTO control_target_events(transition_id,phase,error_code) VALUES(NEW.id,NEW.phase,NEW.error_code); RETURN NEW; END $$;
CREATE TRIGGER target_event AFTER INSERT OR UPDATE ON control_target_transitions FOR EACH ROW EXECUTE FUNCTION record_target_event();
CREATE FUNCTION guard_target_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE t control_target_transitions; c control_target_candidates;
BEGIN
 IF NEW.pending_handover IS NOT NULL AND OLD.pending_handover IS NULL THEN
  SELECT * INTO t FROM control_target_transitions WHERE id=NEW.pending_handover;
  SELECT * INTO c FROM control_target_candidates WHERE id=t.candidate_id;
  IF t.phase IS DISTINCT FROM 'planned' OR t.agent_id IS DISTINCT FROM OLD.agent_id OR c.from_epoch IS DISTINCT FROM OLD.target_epoch OR c.from_contract IS DISTINCT FROM OLD.contract_sha256 OR OLD.pending_request IS NOT NULL OR OLD.enabled OR OLD.replicas<>0 OR NEW.revision<>OLD.revision+1 THEN
   RAISE EXCEPTION 'handover_requires_current_admission' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.contract_sha256 IS DISTINCT FROM OLD.contract_sha256 OR NEW.target_epoch<>OLD.target_epoch THEN
  SELECT * INTO t FROM control_target_transitions WHERE id=OLD.pending_handover;
  SELECT * INTO c FROM control_target_candidates WHERE id=t.candidate_id;
  IF t.phase IS DISTINCT FROM 'applying' OR t.agent_id IS DISTINCT FROM OLD.agent_id
   OR c.from_epoch IS DISTINCT FROM OLD.target_epoch OR c.from_contract IS DISTINCT FROM OLD.contract_sha256
   OR NEW.target_epoch<>OLD.target_epoch+1 OR NEW.contract_sha256 IS DISTINCT FROM c.new_contract
   OR NEW.slot_ids<>OLD.slot_ids OR OLD.capacity<>1 OR NEW.capacity<>1
   OR OLD.enabled OR OLD.replicas<>0 OR OLD.pending_request IS NOT NULL
   OR NEW.enabled OR NEW.replicas<>0 OR NEW.pending_request IS NOT NULL
   OR NEW.observed IS NOT NULL OR NEW.observed_at IS NOT NULL OR NEW.pending_handover IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM control_target_contracts v WHERE v.agent_id=OLD.agent_id AND v.epoch=NEW.target_epoch AND v.transition_id=t.id AND v.contract_sha256=c.new_contract AND v.descriptor=c.new_descriptor)
  THEN RAISE EXCEPTION 'target_pointer_requires_admitted_transition' USING ERRCODE='23514'; END IF;
 ELSIF OLD.pending_handover IS NOT NULL AND (NEW.enabled OR NEW.replicas<>0 OR NEW.pending_request IS NOT NULL OR NEW.pending_handover IS DISTINCT FROM OLD.pending_handover) THEN
  RAISE EXCEPTION 'target_handover_blocks_control' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER target_pointer_guard BEFORE UPDATE ON remote_control_groups FOR EACH ROW EXECUTE FUNCTION guard_target_pointer();
CREATE FUNCTION bind_control_target_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE g remote_control_groups;
BEGIN
 SELECT * INTO g FROM remote_control_groups WHERE agent_id=NEW.agent_id FOR UPDATE;
 IF g.pending_handover IS NOT NULL THEN RAISE EXCEPTION 'target_handover_blocks_control' USING ERRCODE='23514'; END IF;
 NEW.target_epoch=g.target_epoch; RETURN NEW;
END $$;
CREATE TRIGGER control_request_target_epoch BEFORE INSERT ON remote_control_requests FOR EACH ROW EXECUTE FUNCTION bind_control_target_epoch();
CREATE FUNCTION fence_retired_target_signal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r remote_control_requests; g remote_control_groups; b remote_control_batches;
BEGIN
 IF NEW.phase='issuing' AND OLD.phase='planned' THEN
  SELECT * INTO r FROM remote_control_requests WHERE request_id=NEW.request_id;
  SELECT * INTO g FROM remote_control_groups WHERE agent_id=r.agent_id FOR SHARE;
  SELECT * INTO b FROM remote_control_batches WHERE request_id=r.request_id;
  IF g.pending_handover IS NOT NULL OR r.target_epoch<>g.target_epoch OR b.contract_sha256 IS DISTINCT FROM g.contract_sha256 OR g.pending_request IS DISTINCT FROM r.request_id THEN
   RAISE EXCEPTION 'retired_target_signal_blocked' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retired_target_signal_guard BEFORE UPDATE ON remote_control_actions FOR EACH ROW EXECUTE FUNCTION fence_retired_target_signal();
