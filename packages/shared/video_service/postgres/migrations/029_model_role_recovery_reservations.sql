-- Recovery admission facts for exact pending-request reconciliation; append-only.
CREATE TABLE model_role_recovery_reservations (
 owner_id text NOT NULL,request_id text NOT NULL,task_id text NOT NULL,
 packet_sha256 text NOT NULL,admitted_revision integer NOT NULL CHECK(admitted_revision>0),
 attempt_before integer NOT NULL CHECK(attempt_before>=0),created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,request_id),
 FOREIGN KEY(owner_id,request_id)REFERENCES model_role_result_recoveries(owner_id,request_id),
 FOREIGN KEY(task_id)REFERENCES model_role_result_deliveries(task_id)
);
CREATE TRIGGER model_role_recovery_reservation_immutable BEFORE UPDATE OR DELETE ON model_role_recovery_reservations FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
