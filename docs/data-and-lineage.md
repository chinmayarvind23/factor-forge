# Data Model and Lineage

## Canonical entities

### ResearchRun

Durable root of all work: identity, status, budgets, checkpoint version, timestamps, active FactorSpec, and terminal reason.

### Paper

Stable paper identifier, title, authors, year, source, allowed content fields, citation edges, retrieval metadata, and content hash.

### FactorSpec

Versioned executable definition of a factor.

### DatasetVersion

Provider, universe, time range, snapshot time, DVC hash, object hashes, point-in-time policy, corporate-action policy, and license notes.

### Experiment

Links run, hypothesis, FactorSpec, dataset, code, environment, seeds, engine, and execution policy.

### Result

Metrics, terminal state, logs/artifacts, timing, cost, and validation state.

### LineageManifest

Immutable join point for evidence.

## PostgreSQL tables

```text
research_runs
research_state_events
research_approvals
papers
factor_specs
dataset_versions
hypotheses
experiment_specs
experiment_results
validation_results
lean_verifications
artifact_refs
lineage_manifests
eval_runs
eval_case_results
```

Large blobs do not belong in PostgreSQL. Store object references and hashes.

## S3 layout

```text
s3://bucket/
  datasets/<dataset_version>/...
  runs/<run_id>/
    code/
    configs/
    experiments/
    plots/
    reports/
    traces/
    manifests/
  evals/<eval_run_id>/...
```

## DVC

DVC pins dataset snapshots and large research data. A benchmark manifest records the DVC revision and object hashes.

## MLflow

Use MLflow for experiment runs, parameters, metrics, comparisons, artifact references, learned-component registry, and explicit promotion status.

The canonical product run still lives in PostgreSQL so the application is not coupled to MLflow's storage model.

## Neo4j projection

The graph is derived and rebuildable from canonical entities and lineage events. A graph outage cannot corrupt source-of-truth run state.

## Lineage completeness rule

A benchmark run cannot pass if a required link is absent:

```text
research idea
-> normalized brief
-> paper evidence
-> hypothesis
-> FactorSpec version
-> dataset version
-> code hash
-> environment
-> experiment result
-> validator version
-> final verdict
-> report
```

## Hashing

Use SHA-256 for immutable content identity unless an upstream system provides a stronger content-addressed identifier. Never hash secrets into public artifacts.

## Data retention

Public benchmark fixtures can be retained indefinitely when licenses allow it. Provider-derived data follows its license. Sensitive auth/user metadata uses a shorter retention policy than research artifacts.

## Cache relationship

Redis entries carry the canonical version identifier they depend on. Cache invalidation follows version changes rather than time alone.
