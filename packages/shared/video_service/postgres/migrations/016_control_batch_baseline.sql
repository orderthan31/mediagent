-- Host-only immutable-at-creation execution-generation baseline. Old batches stay NULL.
ALTER TABLE remote_control_batches ADD COLUMN baseline jsonb CHECK(baseline IS NULL OR jsonb_typeof(baseline)='array');
