# Data Model and Lineage

## Implemented data foundation

The current data slice stores immutable bytes locally, verifies S3 adapter contracts, and
publishes owner-scoped dataset manifests in PostgreSQL. `ArtifactRef` carries SHA-256, exact
byte length and media type. Both stores verify bytes on every read and reject corrupt existing
objects rather than overwriting them. Local publication uses flushed temporary files and an
atomic hard link, with pinned ancestors that reject symbolic links and Windows reparse points.
S3 uses conditional creation, checksums and bounded requests. Live AWS verification is pending.

`DatasetManifest` binds source vintage, coverage, schema versions, table row counts, content
references, security-ID namespace, timing/action/exit policies and explicit permitted uses.
Canonical JSON determines its SHA-256 version. Unknown rights grant no use; expired retention
blocks publication and reads. DVC references retain the upstream MD5 separately from SHA-256.

`PostgresDatasetCatalog` reuses the canonical database pool. Ingestion requires an explicit
capability, and sharing requires a separate publication capability. Every object must verify
before the owner/version row commits. Rights are checked again after dependency work. Repeated
identical publication is idempotent; changing visibility for an existing publication conflicts.
An uploaded object without committed catalog metadata grants no dataset access. Publication is
not a distributed transaction with object storage, so a crash may leave unreferenced bytes.

The original fictional market in `data/fixtures` tests late filings, amendments, historical
membership, a ticker rename, a split, dividends and known/unknown exit outcomes. Point-in-time
selection enforces availability at or before formation and formation strictly before trading.
These fixtures cannot establish empirical factor replication. Accounting and complete research
lineage remain future stages. The entities and storage layouts below describe the target model
unless identified as implemented here.

`fixture-bundle` saves the complete authorized input and terms, dataset manifest, selection
times, result, installed Python/Pydantic versions, dependency lock and the source modules used
for replay. `verify-bundle` retrieves every declared component and recomputes the result with
the installed trusted code. It never executes stored code. Exact input bytes and canonical
UTF-8/LF code identities make checkout line endings explicit. Replaying under different code,
lock or recorded environment versions fails; restore the matching checkout/environment first.

This fixed-fixture command ties reuse rights to reviewed input and terms hashes. Modified
fixtures need a separately reviewed version. Git metadata records the actual checkout revision
and dirty state, or unknown values when unavailable. Hashes prove content identity and replay
agreement; the bundle is unsigned and does not authenticate who ran it. Its DVC field remains
unset: the separately committed pointer has provenance, but secure DVC execution is blocked by
the [isolated tooling audit](../tools/dvc/README.md). The bundle establishes a reproducible
data check, not complete research-run lineage.

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

The implemented content store uses `<configured-prefix>/sha256/<first-two-hex>/<sha256>`.
The following logical research layout remains planned; manifests will join logical names to
immutable content references.

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
