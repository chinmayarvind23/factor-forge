# ADR-011: Agentic RL and RLVR are a benchmarked post-MVP policy extension

## Context

FactorForge produces structured research states, bounded actions, sandboxed execution, deterministic finance validators, successful and failed trajectories, and complete lineage.

That infrastructure can support reinforcement learning with verifiable rewards and multi-step agentic RL.

A learned policy also creates new risks:

- reward hacking,
- benchmark contamination,
- hidden policy drift,
- unsafe action selection,
- loss of reproducibility,
- optimizing return metrics at the expense of research validity.

## Decision

Add an explicit research environment and RLVR/agentic-RL training path after the deterministic LangGraph baseline, research memory, and eval harness are stable.

The harness remains authoritative. A learned policy can propose bounded research actions but cannot change hard security, data, statistics, budget, or lineage rules.

Use:

```text
prompted baseline
-> supervised trajectory baseline
-> preference learning
-> RLVR on verifiable tasks
-> multi-step agentic RL
-> held-out promotion comparison
```

The public 45-case release benchmark is never used as policy-training data.

## Reward

Prefer deterministic or reference-based verifier signals.

Do not optimize raw Sharpe alone.

Hard failures such as lookahead leakage, sandbox violations, unauthorized tools, invalid methodology, missing lineage, and budget violations override soft reward components.

## Alternatives

### No learned policy

Simple and reproducible, but it leaves the verified trajectory corpus unused as a learning experiment.

### Online self-modification

Rejected because behavior and benchmark evidence become difficult to reproduce.

### End-to-end RL before deterministic baselines

Rejected because reward failures would be difficult to diagnose and a strong non-RL comparison would be missing.

## Tradeoff

The RL environment, reward versioning, rollout storage, training compute, and anti-reward-hacking evals add complexity.

The work is justified only after the base system produces trustworthy trajectories.

## Evidence

Compare policies on:

- autonomous completion,
- valid experiment rate,
- research-quality scorecards,
- out-of-sample robustness,
- redundant experiment rate,
- tool calls,
- iterations,
- runtime,
- LLM cost,
- hard execution-path violations,
- held-out transfer behavior.

## Switch condition

Do not promote an RL policy when it fails to beat the prompted/deterministic baseline under the accepted promotion criteria.

A failed RL experiment is preserved in research memory and published as a learning result rather than hidden.
