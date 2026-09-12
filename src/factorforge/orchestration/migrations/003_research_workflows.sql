CREATE TABLE IF NOT EXISTS research_workflows (
    run_id uuid NOT NULL REFERENCES research_runs(run_id),
    request_sha256 char(64) NOT NULL,
    request_ref text NOT NULL,
    result_ref text NOT NULL,
    budget_ref text NOT NULL,
    completion_ref text,
    remembered boolean NOT NULL DEFAULT false,
    PRIMARY KEY (run_id, request_sha256),
    CHECK (NOT remembered OR completion_ref IS NOT NULL)
);
