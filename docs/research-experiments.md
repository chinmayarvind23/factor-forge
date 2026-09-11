# Source-derived experiment scheduling

`research_experiments` accepts an owner-verified run and an `ExperimentPlan` with
reviewed literature/data bindings, explicit starting capital, a captured evaluation
clock and a per-source LLM allowance. It composes source retrieval, durable
extraction, strategy compilation and experiment execution in ranking order.

Each compiled candidate runs through `MonthlyExperimentGraph`, which persists
execution and publication checkpoints in PostgreSQL. The scheduler obtains final
status through read-only recovery of the canonical settled worker result. Other
candidates retain a `skipped` outcome with their source-stage status as the reason.
An explicit experiment-budget rejection produces `budget_stopped`; authorization,
artifact, checkpoint and unresolved-operation errors propagate for reconciliation.
The scheduler can still recover a later candidate that already completed before
the budget was exhausted.

The final artifact retains the exact plan, the published strategy-stage reference
and ordered experiment result references. A completed experiment means completion
of its declared monthly accounting execution. Statistical validation, research
promotion and published-factor reproduction are subsequent research decisions.

Retry must use the same captured plan. Its evaluation clock and capital form part
of each immutable monthly command. Recomputing deterministic retrieval and drafts
reuses settled model operations; each experiment graph resumes its own saved state.
Changing capital or evaluation time defines a new command subject to the original
run's remaining budget. The scheduler does not reset budgets or infer zero LLM cost.

This version persists per-experiment graph state and worker operations. It recomputes
the bounded source/compilation stages on restart. A single enclosing research graph,
validation and iterative research decisions remain to be composed. Execution uses
the existing trusted original-fixture monthly profile.
