# ADR-010: Learn from trajectories offline

## Context

Successful and failed research runs produce useful training data, but self-modifying online behavior would make reproduction difficult.

## Decision

Export verified trajectories and use PyTorch/TRL to train a narrow component, beginning with FactorSpec extraction or next-action ranking.

Promotion requires a frozen benchmark comparison against the current prompted baseline.

## Tradeoff

Offline learning adapts more slowly than online self-improvement but preserves versioning, rollback, and reproducibility.

## Switch condition

Consider stronger online learning only after versioning, rollback, eval, and governance can preserve reproducibility.
