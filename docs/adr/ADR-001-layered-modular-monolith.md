# ADR-001: Start with a layered modular monolith

## Context

The research workflow is tightly coupled at the domain level while initial API load is small. Premature service boundaries would add auth, networking, retries, deployment, and tracing before the core research loop is trustworthy.

## Decision

Keep the control plane in one Python codebase with strong module boundaries. Split the experiment worker runtime because untrusted-code isolation and compute scaling create a real deployment boundary.

## Alternatives

- full microservices,
- one process including generated-code execution.

## Tradeoff

Control-plane modules cannot scale independently. That is acceptable until measured workloads diverge.

## Switch condition

Extract a service when it has independent scaling, security, runtime, or team-ownership needs that outweigh network and operational cost.
