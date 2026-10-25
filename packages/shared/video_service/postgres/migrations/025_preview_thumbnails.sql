ALTER TABLE video_preview_jobs ADD COLUMN thumbnail_ref jsonb;
ALTER TABLE video_preview_jobs ADD COLUMN thumbnail_verified_at timestamptz;
CREATE FUNCTION preserve_preview_thumbnail()RETURNS trigger LANGUAGE plpgsql AS $$BEGIN
IF OLD.thumbnail_ref IS NOT NULL AND (NEW.thumbnail_ref,NEW.thumbnail_verified_at)IS DISTINCT FROM(OLD.thumbnail_ref,OLD.thumbnail_verified_at)THEN RAISE EXCEPTION 'immutable preview thumbnail';END IF;RETURN NEW;END;$$;
CREATE TRIGGER preview_thumbnail_immutable BEFORE UPDATE ON video_preview_jobs FOR EACH ROW EXECUTE FUNCTION preserve_preview_thumbnail();
