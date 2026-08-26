# Benchmark Methodology

## 45-case suite

### Group A: 15 published-factor replication cases

Measures relevant literature retrieval, critical FactorSpec extraction, executable implementation, statistical reproduction, and LEAN verification.

### Group B: 15 synthesis/composition cases

Examples include combining residual momentum with sector neutralization, testing a quality signal under alternative formation lags, constructing a hybrid factor from two papers, and testing stricter turnover constraints.

### Group C: 15 adversarial/failure cases

Measures whether the system correctly stops, degrades, retries, or rejects unsafe/invalid research.

## Autonomous completion

A case counts as complete when:

- it reaches a valid terminal state,
- no human edits run state, generated code, FactorSpec, or experiment output during evaluation,
- required evidence exists,
- execution-path hard gates pass.

A correct refusal can count as completion in an intentionally impossible or unsafe case.

## Factor-spec extraction

Critical fields are scored separately from optional explanatory fields.

```text
universe
formula
lookback
formation lag
holding period
rebalance
weighting
point-in-time rule
cost model
expected direction
```

A case passes only when all fields declared critical for that paper pass the frozen comparison rule.

## Published-factor reproduction

Before execution, each case freezes its reference, data mapping, time period, cost convention, tolerance, and required statistics. Tolerances cannot be widened after a miss.

## Runtime study

The runtime comparison uses the same case set and equivalent model/provider constraints.

Record baseline harness version, optimized harness version, hardware, worker concurrency, cache state, data snapshot, models, pricing snapshot, wall time per case, model active time, tool active time, and queue time.

## Cost study

Cost uses actual token usage multiplied by a frozen provider price table for the experiment date.

The `$0.84 average LLM cost per paper` means LLM cost

## Span-count study

The 1,200+ span is counted from unique trace/span identifiers in exported LangSmith/OTel benchmark data. Duplicate exports are not new spans.

## Lineage-completeness study

For every benchmark run, the validator checks all required fields and object references.

```text
completeness = complete_runs / benchmark_runs
```

## Reproducibility bundle

A benchmark release includes case definitions, data acquisition instructions or redistributable snapshots, configs, code, environment locks, result JSON, summary tables, trace identifiers, and reproduction commands.

## RL policy benchmark separation

The public 45-case benchmark is a release holdout and is not used to train agent policies.

Agentic-learning experiments maintain separate immutable case IDs for training trajectories, development, RL validation, transfer evaluation, and release evaluation.

A policy artifact records the exact case-set hashes used during training.

The release benchmark runner checks that no release case ID appears in the policy training manifest.
