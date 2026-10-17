-- Sources are declarations of immutable content identity, never mutable local paths.
CREATE TRIGGER source_identity_immutable BEFORE UPDATE OR DELETE ON assets
FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation();
CREATE INDEX assets_owner_created ON assets(owner_id,created_at DESC,id DESC);
