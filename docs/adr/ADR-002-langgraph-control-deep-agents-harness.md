# ADR-002: LangGraph controls lifecycle; Deep Agents handles bounded research work

## Context

Long-horizon research benefits from flexible decomposition, but budget, state, and safety cannot depend on a model remembering instructions.

## Decision

Use LangGraph for state transitions, checkpoints, retries, budgets, and termination. Use Deep Agents for bounded literature synthesis, hypothesis refinement, and critique.

## Alternatives

- one Deep Agent for the complete run,
- custom loop with no agent framework,
- peer-to-peer swarm.

## Tradeoff

Two abstraction layers require explicit ownership rules.

## Evidence

Compare task completion, invalid transition rate, context usage, tool failures, cost, and debugging effort against simpler baselines.

## Switch condition

Change when another runtime demonstrates the same deterministic lifecycle guarantees with materially lower complexity.
