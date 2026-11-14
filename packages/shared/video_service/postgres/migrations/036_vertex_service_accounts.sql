-- Additive immutable revision metadata. No existing row or hash is rewritten.
-- A 32768-byte JSON credential adds a 12-byte nonce and a 16-byte AES-GCM tag.
-- Ordinary API-key validation remains 4096 printable ASCII bytes in CredentialStore.
ALTER TABLE provider_credentials DROP CONSTRAINT provider_credentials_ciphertext_check;
ALTER TABLE provider_credentials ADD CONSTRAINT provider_credentials_ciphertext_check
    CHECK (octet_length(ciphertext) BETWEEN 29 AND 32796);
ALTER TABLE connection_revisions ADD COLUMN vertex_project text;
ALTER TABLE connection_revisions ADD COLUMN vertex_location text;
ALTER TABLE connection_revisions DROP CONSTRAINT connection_revisions_protocol_check;
ALTER TABLE connection_revisions ADD CONSTRAINT connection_revisions_protocol_check
    CHECK (protocol IN ('openai_compatible','openai','anthropic','gemini','vertex_ai'));
ALTER TABLE connection_revisions ADD CONSTRAINT connection_revisions_vertex_config_check
    CHECK (
      (provider <> 'vertex_ai' AND protocol <> 'vertex_ai'
       AND vertex_project IS NULL AND vertex_location IS NULL)
      OR
      (provider = 'vertex_ai' AND protocol = 'vertex_ai'
       AND vertex_project IS NOT NULL AND vertex_location IS NOT NULL
       AND vertex_project ~ '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'
       AND length(vertex_location) <= 63
       AND vertex_location ~ '^(global|[a-z]+(-[a-z]+)+[1-9][0-9]*)$'
       AND endpoint = 'https://' || CASE WHEN vertex_location = 'global'
           THEN 'aiplatform.googleapis.com' ELSE vertex_location || '-aiplatform.googleapis.com' END
           || '/v1/projects/' || vertex_project || '/locations/' || vertex_location || '/publishers/google')
    );
