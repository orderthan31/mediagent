ALTER TABLE jobs ADD COLUMN library_removed_at timestamptz;
ALTER TABLE jobs ADD COLUMN library_removed_by text REFERENCES accounts(id);
ALTER TABLE jobs ADD COLUMN library_removal_reason text;
ALTER TABLE jobs ADD CONSTRAINT job_library_removal_complete CHECK (
(library_removed_at IS NULL AND library_removed_by IS NULL AND library_removal_reason IS NULL) OR
(library_removed_at IS NOT NULL AND library_removed_by IS NOT NULL AND library_removal_reason IS NOT NULL AND length(library_removal_reason) BETWEEN 1 AND 200));
CREATE FUNCTION preserve_processing_job_with_library_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.library_removed_at IS NOT NULL AND ROW(NEW.library_removed_at,NEW.library_removed_by,NEW.library_removal_reason) IS DISTINCT FROM ROW(OLD.library_removed_at,OLD.library_removed_by,OLD.library_removal_reason) THEN
   RAISE EXCEPTION 'Job library removal is immutable' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-ARRAY['library_removed_at','library_removed_by','library_removal_reason']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['library_removed_at','library_removed_by','library_removal_reason']) THEN RETURN NEW;END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM job_processing_cases WHERE owner_id=OLD.owner_id AND job_id=OLD.id)THEN
  RAISE EXCEPTION 'Processing review preserves original facts' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE'THEN RETURN OLD;END IF;RETURN NEW;
END;$$;
CREATE OR REPLACE TRIGGER preserve_processing_job BEFORE DELETE OR UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION preserve_processing_job_with_library_removal();
