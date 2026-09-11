CREATE TABLE IF NOT EXISTS research_budgets (
    run_id uuid PRIMARY KEY REFERENCES research_runs(run_id),
    ledger_json text NOT NULL CHECK (octet_length(ledger_json) <= 131072)
);
