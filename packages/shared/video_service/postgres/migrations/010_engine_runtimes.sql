-- Physical engine identities are platform metadata, never user/provider keys.
CREATE TABLE engine_runtime_revisions (
    role text NOT NULL CHECK (role IN ('transcribe','translate','preprocess_audio','faceswap')),
    revision bigint NOT NULL CHECK (revision > 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    descriptor jsonb NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role,revision)
);
CREATE TABLE engine_runtime_heads (
    role text PRIMARY KEY,
    revision bigint NOT NULL,
    FOREIGN KEY (role,revision) REFERENCES engine_runtime_revisions(role,revision)
);
