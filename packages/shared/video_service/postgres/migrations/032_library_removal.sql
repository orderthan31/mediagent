-- Library removal retains immutable source data and saved workflow/job history.
-- The application receives no new grants or mutation authority.
ALTER TABLE assets ADD COLUMN library_removed_at timestamptz;
ALTER TABLE assets ADD COLUMN library_removed_by text REFERENCES accounts(id);
ALTER TABLE assets ADD COLUMN library_removal_reason text;
ALTER TABLE workflows ADD COLUMN library_removed_at timestamptz;
ALTER TABLE workflows ADD COLUMN library_removed_by text REFERENCES accounts(id);
ALTER TABLE workflows ADD COLUMN library_removal_reason text;
ALTER TABLE assets ADD CONSTRAINT asset_library_removal_complete CHECK (
 (library_removed_at IS NULL AND library_removed_by IS NULL AND library_removal_reason IS NULL) OR
 (library_removed_at IS NOT NULL AND library_removed_by IS NOT NULL AND library_removal_reason IS NOT NULL AND length(library_removal_reason) BETWEEN 1 AND 200));
ALTER TABLE workflows ADD CONSTRAINT workflow_library_removal_complete CHECK (
 (library_removed_at IS NULL AND library_removed_by IS NULL AND library_removal_reason IS NULL) OR
 (library_removed_at IS NOT NULL AND library_removed_by IS NOT NULL AND library_removal_reason IS NOT NULL AND length(library_removal_reason) BETWEEN 1 AND 200));

CREATE FUNCTION protect_source_with_library_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'Source identity is immutable' USING ERRCODE='23514';
 END IF;
 IF (to_jsonb(NEW)-ARRAY['library_removed_at','library_removed_by','library_removal_reason'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['library_removed_at','library_removed_by','library_removal_reason']) THEN
  RAISE EXCEPTION 'Source identity is immutable' USING ERRCODE='23514';
 END IF;
 IF OLD.library_removed_at IS NOT NULL AND
 ROW(NEW.library_removed_at,NEW.library_removed_by,NEW.library_removal_reason)
 IS DISTINCT FROM ROW(OLD.library_removed_at,OLD.library_removed_by,OLD.library_removal_reason) THEN
  RAISE EXCEPTION 'Library removal is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END; $$;
CREATE OR REPLACE TRIGGER source_identity_immutable BEFORE UPDATE OR DELETE ON assets
 FOR EACH ROW EXECUTE FUNCTION protect_source_with_library_removal();

CREATE FUNCTION protect_workflow_library_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'Use library removal to preserve workflow history' USING ERRCODE='23514';
 END IF;
 IF OLD.library_removed_at IS NOT NULL AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
  RAISE EXCEPTION 'Removed workflow is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER workflow_library_removal_immutable BEFORE UPDATE OR DELETE ON workflows
 FOR EACH ROW EXECUTE FUNCTION protect_workflow_library_removal();
