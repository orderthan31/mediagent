-- Preserve original rows and immutable snapshots; separate execution actor from asset origin.
-- Old snapshots have no uploaded_by: their original owner remains the source owner.
ALTER TABLE jobs ADD COLUMN asset_owner_id text GENERATED ALWAYS AS
    (COALESCE(snapshot->'asset'->>'uploaded_by',owner_id)) STORED;
ALTER TABLE jobs DROP CONSTRAINT jobs_owner_id_asset_id_fkey;
ALTER TABLE jobs ADD CONSTRAINT jobs_asset_origin_fkey
    FOREIGN KEY(asset_owner_id,asset_id) REFERENCES assets(owner_id,id);
