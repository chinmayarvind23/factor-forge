# Failure Modes

## Input and planning

### Vague idea cannot become executable

Return a structured clarification requirement or terminate as insufficiently specified.

### Hypothesis generator repeats near duplicates

Apply novelty filtering, candidate caps, and an explicit stop reason.

## Literature

### Search provider unavailable

Bounded retry. Use a versioned approved cache only when provenance is recorded; otherwise stop.

### Conflicting factor definitions

Preserve both sources, flag conflict, and do not silently choose.

### Prompt injection in paper text

Treat source content as data. Tool policy does not change.

## Data

### Missing point-in-time semantics

Terminal `DATA_INVALID`.

### Future information detected

Hard failure for that experiment.

### Survivorship/delisting coverage unknown

Mark the methodological limitation or reject the benchmark case according to frozen rules.

## Experiments

### Crash

Capture stderr, mark terminal `crash`, optionally permit a bounded repair attempt.

### Timeout

Kill job, preserve partial logs, mark `timeout`.

### OOM

Kill job and record resource class/peak memory.

### Network exfiltration attempt

Runtime blocks it, emits a security event, and marks `security_block`.

### Duplicate SQS delivery

Idempotency key prevents duplicate accepted results.

## Quant validation

### In-sample result collapses out of sample

Verdict becomes `UNSTABLE` or `UNSUPPORTED`.

### Costs erase returns

Report gross and net results and do not promote.

### LEAN disagrees with fast engine

Use `VERIFICATION_DISAGREEMENT` and investigate.

### Repeated testing inflates significance

Record hypothesis count/selection and apply declared multiplicity handling.

## Agent runtime

### Model provider outage

Checkpoint, then bounded retry or approved fallback with model identity preserved.

### Runaway loop

Hard iteration, wall-clock, and cost brakes terminate it.

### Critic does not converge

Plateau or max-round stop with trace.

### Peer agent returns unsafe instruction

Parse as typed data, never execute directly.

## Storage

### Redis unavailable

Cache miss path and degraded telemetry.

### Neo4j unavailable

Continue without graph enrichment when canonical state is sufficient.

### RDS unavailable

Do not acknowledge a state transition.

### S3 unavailable

Do not mark an experiment complete because artifacts are not durable.

## Observability

### LangSmith unavailable

OTel/system telemetry continues; semantic trace export can retry later if policy allows.

### Sensitive field enters telemetry

Redaction gate blocks export and records a safe diagnostic.

## Release evidence

### Missing lineage field

The case fails its evidence gate even if the output looks correct.

### Metric cannot be reproduced

The public result is not updated.
