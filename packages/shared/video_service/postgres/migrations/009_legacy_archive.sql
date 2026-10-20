-- Legacy records are archival and deliberately have no new account/job foreign key.
CREATE TABLE legacy_import_snapshots (
    snapshot_id text PRIMARY KEY CHECK (snapshot_id ~ '^[a-f0-9]{64}$'),
    namespace text NOT NULL,
    index_counts jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE legacy_archive_records (
    namespace text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('job','index','workflow','settings','asset')),
    record_id text NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    snapshot_id text NOT NULL REFERENCES legacy_import_snapshots(snapshot_id),
    classification text NOT NULL CHECK (classification = 'legacy/unassigned'),
    internal boolean NOT NULL,
    legacy_state text,
    payload jsonb NOT NULL,
    artifact_references jsonb NOT NULL,
    PRIMARY KEY (namespace,kind,record_id)
);
CREATE FUNCTION reject_legacy_archive_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'legacy_archive_is_immutable';
END;
$$;
CREATE TRIGGER legacy_archive_immutable BEFORE UPDATE OR DELETE ON legacy_archive_records
    FOR EACH ROW EXECUTE FUNCTION reject_legacy_archive_mutation();
