-- asset_owner_id is GENERATED ALWAYS from immutable snapshot/owner inputs and is unset in BEFORE triggers.
CREATE OR REPLACE FUNCTION preserve_processing_job_with_library_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.library_removed_at IS NOT NULL AND ROW(NEW.library_removed_at,NEW.library_removed_by,NEW.library_removal_reason) IS DISTINCT FROM ROW(OLD.library_removed_at,OLD.library_removed_by,OLD.library_removal_reason) THEN
   RAISE EXCEPTION 'Job library removal is immutable' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-ARRAY['library_removed_at','library_removed_by','library_removal_reason','asset_owner_id']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['library_removed_at','library_removed_by','library_removal_reason','asset_owner_id']) THEN RETURN NEW;END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM job_processing_cases WHERE owner_id=OLD.owner_id AND job_id=OLD.id)THEN
  RAISE EXCEPTION 'Processing review preserves original facts' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE'THEN RETURN OLD;END IF;RETURN NEW;
END;$$;
