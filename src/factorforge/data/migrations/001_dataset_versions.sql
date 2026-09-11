CREATE TABLE IF NOT EXISTS dataset_versions (
    owner_issuer text NOT NULL,
    owner_subject text NOT NULL,
    version_id char(64) NOT NULL,
    manifest jsonb NOT NULL,
    shared boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (owner_issuer, owner_subject, version_id)
);
CREATE INDEX IF NOT EXISTS dataset_versions_shared
    ON dataset_versions (version_id) WHERE shared;
