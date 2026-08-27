# Reproducibility

## Principle

A result is useful only if a future reviewer can identify what was run.

## Run bundle

```text
manifest.json
research_brief.json
factor_spec.json
dataset_manifest.json
environment.json
prompts/
generated_code/
configs/
experiments/
validation/
lean/
report/
trace_refs.json
```

## Determinism

Where deterministic behavior is possible, use a stable data snapshot, stable code, pinned dependencies, fixed seeds, and fixed accounting/metric implementations.

Model output can remain stochastic. Record model/version, prompt version, decoding parameters, and output.

## Environment

Record Python version, package-lock hash, OS/container digest, CPU architecture, important native libraries, LEAN version, R version/packages, and Spark version when used.

## Data

Record DVC revision, provider/snapshot ID, source hashes, point-in-time policy, time range, and universe definition.

## Research code

Generated code is immutable after an experiment starts. A repair creates a new code hash and experiment ID.

## Reproduction levels

### Exact

Same data, deterministic code, seed, and environment reproduce matching numerical output within machine tolerance.

### Statistical

Stochastic training/provider behavior reproduces the same benchmark conclusion within declared tolerance.

### Methodological

External data is no longer available, but exact methodology, versions, and source identifiers remain reconstructable.

Public benchmark claims prefer exact or statistical reproduction.
