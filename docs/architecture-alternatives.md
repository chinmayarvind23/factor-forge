# Architecture Alternatives and Tradeoffs

## Decision frame

The design optimizes for quant research correctness, and agent reliability. An architecture that makes the first useful research loop materially harder must justify itself with a real requirement.

## Agent architecture

### One model, one prompt, many tools

Rejected for the production path. It puts workflow state and control flow in model context, grows the tool-selection surface, and makes long-run replay difficult.

### Independent swarm with peer-to-peer coordination

Rejected for the core path. Shared state, conflicting writes, permission inheritance, and reproducible grading become harder.

### LangGraph state machine plus bounded Deep Agents

Selected. LangGraph owns lifecycle and policy. Deep Agents receives narrow research assignments with fresh context.

Switch when another runtime can demonstrate equivalent transition auditability and deterministic lifecycle controls with materially lower complexity.

## Backtesting architecture

### LEAN for every experiment

Strong realism, slower iteration and harder inspection for small factor mutations.

### Polars engine only

Fast and transparent, but self-confirming if accounting or timing code is wrong.

### Polars fast engine plus LEAN verification

Selected. Use the transparent fast engine for research breadth, then independently implement promoted strategies in LEAN.

## Data processing

Pandas-only is simple but less compelling for larger columnar research. PySpark-everywhere is operationally heavy for small local experiments.

Selected: Polars primary, PySpark for large backfills, joins, and scale benchmarks.

## Durable state

Neo4j is graph-friendly but state transitions, approvals, idempotency, and manifests fit relational transactions better.

Selected: PostgreSQL source of truth and Neo4j as a rebuildable derived graph.

## Search

Selected split:

- Elasticsearch for hybrid text retrieval,
- Neo4j for relationship traversal,
- Weaviate for dense-vector comparison.

Keep Weaviate only if its benchmark gain justifies a third derived retrieval system.

## Queue

Kafka is not selected for low-rate durable experiment dispatch. Redis is not the durable queue.

Selected: SQS for experiment jobs, Kafka for a separate market-data replay/streaming lab.

## Kubernetes

Kubernetes is rejected because it delays research correctness. No Kubernetes at all is also incomplete once parallel generated-code experiments need resource isolation and restart policy.

Selected: Docker local first, EKS worker plane later.

## Agent interoperability

A2A everywhere would turn in-process interactions into network problems.

Selected: native LangGraph/Deep Agents subagents for the core path plus one bounded remote Google ADK specialist over A2A.

## Tool interoperability

MCP is used at stable tool boundaries such as literature, data catalog, and experiment lookup. Native Python tools remain appropriate for internal hot-path operations.

## Agentic learning

### Offline supervised trajectory learning only

Safe and simple, but it does not test whether environment feedback can improve sequential research decisions.

### Online self-modification

Rejected. A policy that silently changes during production makes benchmark evidence and incident reproduction harder.

### Direct end-to-end RL before a deterministic baseline

Rejected. Reward failures would be difficult to diagnose, and the system would have no strong non-RL comparison.

### Selected: staged trajectory learning, RLVR, and agentic RL

```text
prompted deterministic baseline
-> supervised trajectory baseline
-> preference learning
-> RLVR on verifiable decisions
-> multi-step research environment
-> held-out policy comparison
```

The production harness remains authoritative.

The 45-case benchmark stays outside training.

A learned policy is rejected when it improves soft reward by exploiting lookahead leakage, transaction-cost omissions, skipped validation, incomplete lineage, or another hard-path failure.
