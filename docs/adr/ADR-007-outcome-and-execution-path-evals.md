# ADR-007: Grade outcome and execution path separately

## Context

An agent can reach a correct-looking result through an invalid research path.

## Decision

Keep two scorecards. Outcome grades research quality. Execution-path grades security, data timing, tool use, budget, sandbox, validator use, and lineage.

## Rule

A hard execution-path violation cannot be hidden by a strong outcome score.

## Alternatives

- one blended score,
- LLM judge only.

## Tradeoff

More graders and case annotations are required, but failures become actionable and safety invariants remain visible.
