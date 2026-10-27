-- Controller-side artifact/adoption delivery journal, never a model rerun queue.
CREATE TABLE model_role_result_deliveries (
 task_id text PRIMARY KEY REFERENCES model_role_tasks(task_id),packet jsonb NOT NULL,
 packet_sha256 text NOT NULL,state text NOT NULL DEFAULT 'ready'CHECK(state IN ('ready','receiving','held','settled','rejected')),
 attempts integer NOT NULL DEFAULT 0,revision integer NOT NULL DEFAULT 1,error_code text
);
CREATE FUNCTION protect_model_role_result_delivery()RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.task_id IS DISTINCT FROM OLD.task_id OR NEW.packet IS DISTINCT FROM OLD.packet OR NEW.packet_sha256 IS DISTINCT FROM OLD.packet_sha256 OR NEW.attempts<OLD.attempts OR NEW.revision<OLD.revision THEN
 RAISE EXCEPTION 'Role result delivery identity/budget is immutable' USING ERRCODE='23514';END IF;
 RETURN NEW;END;$$;
CREATE TRIGGER model_role_result_delivery_immutable BEFORE UPDATE ON model_role_result_deliveries FOR EACH ROW EXECUTE FUNCTION protect_model_role_result_delivery();
CREATE TRIGGER model_role_result_delivery_no_delete BEFORE DELETE ON model_role_result_deliveries FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE TABLE model_role_result_recoveries (
 owner_id text NOT NULL,request_id text NOT NULL,task_id text NOT NULL REFERENCES model_role_tasks(task_id),
 request_sha256 text NOT NULL,response jsonb,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(owner_id,request_id)
);
CREATE TRIGGER model_role_result_recovery_no_delete BEFORE DELETE ON model_role_result_recoveries FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();

CREATE FUNCTION protect_model_role_result_recovery()RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.owner_id,NEW.request_id,NEW.task_id,NEW.request_sha256)IS DISTINCT FROM ROW(OLD.owner_id,OLD.request_id,OLD.task_id,OLD.request_sha256)
 OR (OLD.response IS NOT NULL AND NEW.response IS DISTINCT FROM OLD.response)THEN
 RAISE EXCEPTION 'Role result recovery identity is immutable' USING ERRCODE='23514';END IF;
 RETURN NEW;END;$$;
CREATE TRIGGER model_role_result_recovery_immutable BEFORE UPDATE ON model_role_result_recoveries FOR EACH ROW EXECUTE FUNCTION protect_model_role_result_recovery();
