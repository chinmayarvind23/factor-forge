# ADR-009: Use MLflow for experiments and DVC for data versioning

## Decision

DVC pins dataset snapshots and large research data versions. MLflow tracks experiment parameters, metrics, artifact references, learned components, and promotion metadata.

PostgreSQL/S3 remain the product source of truth.

## Tradeoff

Lineage spans multiple systems, so the FactorForge manifest must join stable identifiers.

## Acceptance

Every benchmark run resolves the DVC, MLflow, git, artifact, model, prompt, and trace identifiers it references.
