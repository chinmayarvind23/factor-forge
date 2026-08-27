# FactorForge Agent Harness

## Principle

The model is one component. Production behavior comes from the scaffold around it.

FactorForge treats these as explicit harness layers:

1. execution environment,
2. tool interface,
3. context assembly,
4. orchestration and lifecycle,
5. state and memory,
6. observability,
7. verification,
8. permission and budget boundaries.

## Execution environment

Generated research code runs in a sandbox.

Local Docker policy:

```text
non-root
no host Docker socket
no network by default
read-only root filesystem where practical
read-only dataset mount
bounded writable scratch
CPU limit
memory limit
PID limit
wall-clock limit
```

Cloud policy maps the same contract to EKS Jobs.

## Tool interface

Prefer a small tool set over a large ambiguous catalog.

Core research tools:

```text
search_literature
read_paper_record
lookup_dataset
load_prior_experiments
submit_experiment
read_experiment_result
run_validator
request_lean_verification
write_research_note
```

Tools are typed with Pydantic. Malformed calls fail before side effects.

The design borrows Pi's minimal-tool lesson: capabilities should be composable and obvious. FactorForge still uses MCP when a standardized external tool boundary adds real value.

## Context assembly

Each model call receives only the state needed for its job:

```text
step objective
current structured state
relevant paper evidence
selected prior memory
FactorSpec
remaining budget
allowed tools
failure feedback
```

Old transcripts, raw logs, and unrelated failed branches are not automatically appended.

## Orchestration

LangGraph owns the loop and enforces legal transitions, iteration caps, deadlines, budgets, checkpoints, approval gates, capability policy, and terminal conditions.

The planner chooses among allowed next actions. It cannot create a new lifecycle state.

## Plan in state

A long research plan is persisted as structured data:

```text
ResearchPlan
  objective
  hypotheses[]
  pending_experiments[]
  completed_experiments[]
  decision_log[]
  remaining_budget
  next_allowed_actions[]
```

The plan survives model-context compaction and process restart.

## Deep Agents

Deep Agents receives bounded assignments such as:

- synthesize five papers into a factor definition,
- compare conflicting factor formulations,
- propose three testable variations,
- critique a result against its evidence,
- produce a compact typed handoff.

A subagent gets isolated context and returns a typed result.

## Recursive decomposition lab

Recursive Language Model and recursive-harness ideas are useful for paper collections or trace corpora too large for one context window.

FactorForge keeps this bounded:

```text
large corpus
-> deterministic partition/search
-> small subagent queries
-> typed findings
-> deterministic reduce/dedup
```

Recursion depth and fan-out are enforced in code.

## Autoresearch loop

The autoresearch-inspired loop narrows what the agent may mutate.

```text
fixed:
dataset snapshot
evaluation windows
accounting implementation
metric implementation
budget

mutable:
factor formula
normalization
neutralization
formation window
holding window
weighting config
generated strategy code
```

Each experiment:

```text
propose
-> execute
-> verify
-> compare with baseline
-> keep or reject
-> append ledger
```

The agent cannot edit the metric implementation that decides whether its experiment improved.

## Verification order

1. deterministic contract checks,
2. numerical/statistical validators,
3. reference-data/gold comparisons,
4. semantic evaluators such as DeepEval,
5. model judge for criteria that cannot be deterministic,

A judge cannot override leakage or security failure.

## Permission boundary

Risk classes:

```text
R0: read approved research data
R1: write run-scoped artifacts
R2: start bounded local experiment
R3: start paid/cloud experiment
R4: change shared infrastructure or delete durable artifacts
R5: capital movement or live trading
```

Default policy:

```text
R0-R2: automatic when authorized
R3: automatic only under configured budget, otherwise approval
R4: human approval
R5: unavailable
```

## Reliability

Retry only transient failures.

```text
429, 502, 503, timeout -> bounded retry with exponential backoff + jitter
400 schema error         -> no blind retry
401/403                  -> no retry until auth changes
security block           -> terminal
```

Checkpoint after brief normalization, literature retrieval, hypothesis queue creation, plan acceptance, each experiment result, validation, LEAN verification, and report completion.

## Tool utility

Useful diagnostics:

```text
tool_advance_rate = calls_that_advance_state / total_calls
```

Also track invalid-call rate, retry rate, mean latency, mean cost, and duplicate-call rate.

Removing a low-value tool is a valid optimization.

## Harness evolution

Prompt, tool, memory, and orchestration changes are versioned and evaluated on the development set, a held-out transfer set, adversarial cases, cost, and latency.

A change that improves one benchmark while degrading held-out cases is not automatically accepted.

## Learned policy boundary

Agentic RL changes the policy proposal layer, not the outer harness.

```text
learned policy
    |
proposed typed action
    |
hard harness
    +--> capability check
    +--> budget gate
    +--> sandbox policy
    +--> point-in-time validator
    +--> quant/statistical validators
    +--> lineage gate
    |
execution
```

The same hard harness is used by prompted, supervised, preference-trained, RLVR, and multi-step RL policies.
