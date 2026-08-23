# Quality Gates

## Python

- Ruff format/check
- mypy strict
- pytest
- coverage
- selected mutation tests
- dependency/security scan

Guidelines:

```text
cyclomatic complexity <= 10 for production functions
roughly <= 50 logical lines per function unless splitting hurts clarity
>= 85% deterministic-core coverage
>= 95% for budget, sandbox-policy, point-in-time, accounting, lineage, auth/permission code
```

Coverage is a floor, not proof of correctness.

## TypeScript

- strict TypeScript
- no unchecked indexed access
- Biome or equivalent lint/format
- Bun tests
- Playwright for critical web flows
- screenshot/visual regression where UI state matters

## Quant code

Required tests cover return accounting, lag semantics, as-of joins, cost model, turnover, missing data, rebalance timing, corporate actions, walk-forward splitter, purge/embargo, HAC math against a reference, and LEAN translation fixtures.

## Agent code

Required tests/evals cover state transitions, stop conditions, budget gates, tool schema validation, capability filtering, retry classes, checkpoint/resume, peer-agent data boundary, context assembly, and deterministic path graders.

## Sandbox

Red-team cases include network attempt, host-file attempt, fork/process bomb, memory exhaustion, wall-clock timeout, large-output attempt, and forbidden commands/dependencies where policy applies.

## Infrastructure

- Terraform fmt/validate
- policy/static scan
- container scan
- Kubernetes schema/policy checks
- least-privilege review

## Release

A release cannot pass with a failing hard security invariant, missing benchmark evidence, incomplete lineage, hidden human correction, post-result benchmark relabeling/tolerance changes, or a public metric unsupported by a saved run.

## RL environment and policy

Required tests:

- deterministic environment reset for pinned fixtures,
- legal-action mask,
- invalid-action rejection,
- reward-component unit tests,
- reward version reproducibility,
- hard-failure override,
- trajectory serialization,
- policy/version lineage,
- training/release case separation,
- held-out policy comparison,
- reward-hacking adversarial suite,
- fallback to prompted policy.

No policy can be promoted by reward alone. Hard execution-path gates remain mandatory.
