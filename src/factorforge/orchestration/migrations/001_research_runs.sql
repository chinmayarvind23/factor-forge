CREATE TABLE IF NOT EXISTS research_runs (
    run_id uuid PRIMARY KEY,
    owner_issuer text NOT NULL,
    owner_subject text NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    request_json jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('RECEIVED', 'BRIEF_NORMALIZED')),
    normalized_brief text,
    graph_version text NOT NULL,
    state_version integer NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    accepted_checkpoint_id text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (owner_issuer, owner_subject, idempotency_key)
);
CREATE TABLE IF NOT EXISTS research_state_events (
    run_id uuid NOT NULL REFERENCES research_runs(run_id),
    state_version integer NOT NULL,
    status text NOT NULL CHECK (status IN ('RECEIVED', 'BRIEF_NORMALIZED')),
    created_at timestamptz NOT NULL,
    checkpoint_id text,
    PRIMARY KEY (run_id, state_version),
    UNIQUE (run_id, status)
);
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS recovery_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS last_recovery_at timestamptz;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS recovery_error_code varchar(64);
