-- Original browser uploads only.006 bytes/checksum remain immutable.
-- Apply this migration explicitly; do NOT run all pending migrations (020 is unrelated).
SET LOCAL lock_timeout = '5s';
ALTER TABLE source_uploads DROP CONSTRAINT source_uploads_expected_size_check;
ALTER TABLE source_uploads ADD CONSTRAINT source_uploads_expected_size_check
 CHECK(expected_size > 0 AND expected_size <= 4294967296) NOT VALID;
ALTER TABLE source_uploads VALIDATE CONSTRAINT source_uploads_expected_size_check;
