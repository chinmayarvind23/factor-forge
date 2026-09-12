# Multi-source hybrid experiments

The hybrid compiler combines two to four supplied source strategies into one executable
monthly strategy. Each component has an explicit positive rational weight; weights sum
exactly to one. Low-is-good formulas are negated before combining them into a long-high
score. The original formulas, weights, parent strategies and source references remain
in the artifact closure.

Parents must share execution timing, market/universe data, costs, portfolio rules,
evaluation settings and signal units. Their signal bindings merge only when each name
has one meaning. Incompatible parents produce a held draft with explicit reasons.
The resulting expression passes the existing bounded arithmetic and dimensional checks.
No Python evaluation, fitted weights or implicit standardization is introduced.

Score comparability is explicitly declared by the caller. Matching units alone does
not prove comparable distributions, and this initial policy does not rank-normalize
or optimize weights. The proposal requires substantive out-of-sample evaluation before
any investment-performance claim. Automatic multi-paper synthesis is separate work.

## Run the original two-signal example

Use the existing PostgreSQL setup and set `RDS_DSN` as in the research-command guide.
Create a directory for your request, then run from the repository root:

```powershell
uv run python scripts/prepare_hybrid_example.py --artifacts artifacts/hybrid --request hybrid-request.json
uv run python -m factorforge.orchestration.hybrid_command --request hybrid-request.json --artifacts artifacts/hybrid
```

The preparation command writes an exclusive request file and publishes original inputs.
The execution command creates a stable owner-scoped run, compiles the proposal, runs the
existing PostgreSQL-checkpointed monthly graph, and retains the budget, report and result.
Retry the execution command with identical inputs to recover settled accounting.
Held compositions consume no experiment operation. A compiled strategy consumes one;
no model calls are made by this supplied-proposal command.

The example uses two fictional securities and independently authored scores:

| Security | Score | Quality | 75% score + 25% quality |
|---|---:|---:|---:|
| A | 2 | 1 | 1.75 |
| B | 1 | 3 | 1.50 |

The blend ranks A above B, obtains the declared short permission for B and follows the
original market fixture's accounting path. With $1,002 capital, terminal liquidation
NAV is $1,057.98 after the declared fees. This is an original execution fixture, not a
published-factor replication. The [free demo](https://huggingface.co/spaces/chinmayarvind/factorforge)
includes this saved hybrid result alongside the single-signal example and precision guard.
