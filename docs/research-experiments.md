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

Plans can request a [retained-result HAC diagnostic](hac-validation.md) with
`hac_lags` and `hac_correction`. The scheduler invokes it only after canonical
monthly settlement has been recovered, and retains its artifact in the ordered
experiment outcome. Statistical computation adds no model call or experiment dispatch.

`ReviewedExperimentPlan` (`research-experiment-plan-v2`) wraps that execution plan
with `max_cost_per_review_microusd`. It adds a [source-only direction review](direction-review.md)
before monthly dispatch. The version-two result contains the unchanged execution
inventory shape plus the review policy and candidate-indexed review references.
Only supported matching judgments proceed; other judgments remain explicit skipped
outcomes, with both original extraction and review evidence retained. Existing
version-one requests retain their canonical identities and replay behavior.
