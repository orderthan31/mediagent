-- Logical upload cancellation; immutable uploaded parts/originals are retained.
ALTER TABLE source_uploads ADD COLUMN cancelled_at timestamptz;
ALTER TABLE source_uploads ADD COLUMN cancelled_by text REFERENCES accounts(id);
ALTER TABLE source_uploads ADD CONSTRAINT upload_cancel_pair CHECK((cancelled_at IS NULL)=(cancelled_by IS NULL));
CREATE FUNCTION preserve_upload_cancel() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.cancelled_at IS NOT NULL AND (NEW.cancelled_at,NEW.cancelled_by,NEW.asset_id,NEW.uploaded_bytes) IS DISTINCT FROM (OLD.cancelled_at,OLD.cancelled_by,OLD.asset_id,OLD.uploaded_bytes) THEN RAISE EXCEPTION 'cancelled upload is immutable';END IF;
 RETURN NEW;
END;$$;
CREATE TRIGGER upload_cancel_immutable BEFORE UPDATE ON source_uploads FOR EACH ROW EXECUTE FUNCTION preserve_upload_cancel();
