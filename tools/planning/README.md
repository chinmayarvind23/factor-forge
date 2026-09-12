# Bounded Deep Agents planning

This opt-in planner turns an investment idea into literature queries, testable
hypotheses and proposed validation steps. It uses Deep Agents 0.7.13, an in-memory
notebook and the existing PostgreSQL budget ledger. The output is a proposal for
review, not a FactorSpec, a backtest or an authorization to run an experiment.

```powershell
uv sync --project tools/planning --locked
# Set RDS_DSN for your local FactorForge PostgreSQL database.
uv run --project tools/planning --locked python tools/planning/planner.py --idea "Investigate equity momentum after transaction costs" --artifacts artifacts/planning --output planning-result.json
```

The local Ollama runtime must have `qwen3:8b` installed. This command downloads no
model and uses no paid provider. The named planning profile uses 8192 context tokens,
768 output tokens, an 8192-byte request cap and a 120-second transport read cap.
Extraction keeps its existing profile. The planner allows at most two model steps;
each reserves one dollar of capacity before dispatch, while actual local billing
uses the local-provider billing classification. The research brief's shared cost and wall-time limits
still apply. The output path must be new.

The model adapter accepts two disjoint actions: write one note at `/research-plan.md`
in Deep Agents' `StateBackend`, or finish with a typed proposal. No model action can
select another path, call a shell, delegate a task or dispatch an experiment. Although
Deep Agents builds its standard tool catalog, this adapter emits only the fixed
notebook tool call. Its recorded JSON protocol and fixed system prompt define the
model-facing action vocabulary. Notebook content remains in graph state and is included
in the next recorded model request.

A restart reconstructs the graph from saved model observations. Identical steps replay
their canonical receipts; an interrupted, unsettled reservation requires reconciliation.
The planner does not silently retry providers or repair their answers. Generation,
parse and graph failures retain a held result with the original budget/evidence.
Proposals need source review and semantic evaluation before downstream execution.

## Verification

Check notebook-to-proposal transitions, invalid actions, budget exhaustion and
interrupted generation against a FactorForge test database using a fresh output
directory:

```powershell
uv run --project tools/planning --locked python tools/planning/verify_planner.py --output artifacts/planning-check
```

The verifier reads `FACTORFORGE_TEST_DSN`, creates an isolated generated test schema,
and retains controlled-provider receipts for inspecting framework and budget behavior.

`factorforge.lineage.trajectories` accepts the planning result root and preserves the
actual prompts/responses for later review. Exports remain unreviewed training material.

The [Deep Agents customization documentation](https://docs.langchain.com/oss/python/deepagents/customization)
describes custom models and backends. The implementation uses an explicit custom
model adapter and `StateBackend`, without a host filesystem backend.
