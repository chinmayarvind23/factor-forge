# Local MLflow research tracking

This isolated, locked environment uses MLflow to track verified research operations.
The exporter reads a `TrajectoryRequest`, verifies and exports the source history,
and writes its metrics, trajectory JSONL, manifest and complete reachable artifact
closure into a local SQLite-backed MLflow experiment. It invokes no model or backtest.

```powershell
uv sync --project tools/tracking --locked
uv run --project tools/tracking --locked pip-audit
uv run --project tools/tracking --locked python tools/tracking/mlflow_export.py --request trajectory-request.json --source-artifacts artifacts/research --database artifacts/tracking.sqlite --tracking-artifacts artifacts/mlflow --receipt tracking-receipt.json
```

See [trajectory requests](../../docs/research-trajectories.md) for the input format.
The supplied root must be a supported saved research result or budget. The projection
records operation counts, actual retained model-attempt counts, pending operations,
missing provider evidence, verified object count and verified byte count. These are
evidence-inventory metrics, not research accuracy or economic performance.

MLflow is a derived tracking view. Content-addressed artifacts remain authoritative.
After logging, the exporter reads metrics and every artifact back and checks their
values, sizes and SHA-256 identities. Repeating an export serially finds the existing
finished projection and verifies it without creating another run. Interrupted exports
stay explicit and require inspection; concurrent exports are not guaranteed to deduplicate.

Use a private directory: exported trajectories may contain source text and model
prompts. This command accepts local database/artifact paths and does not configure
a hosted tracking service or publish the corpus. `mlflow-skinny` supplies the tracking
SDK; this environment does not include the full MLflow web UI server.

The initial real SDK/SQLite check exported five model operations and 64 verified objects.
Serial replay reused one run, a modified manifest was detected, and restored artifacts
passed readback with model dispatch forbidden. The initial MLflow-only environment's
dependency audit passed. The [Neo4j adapter](NEO4J.md) expands this tool environment;
its real Community-server checks passed, and the expanded Python environment audit
completed through OSV with 110 dependencies, no reported vulnerabilities and no skips.

MLflow's [backend-store documentation](https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/)
describes SQLite tracking storage; its [tracking API](https://mlflow.org/docs/latest/ml/tracking/)
documents experiment metrics and artifacts.

## Historical study tracking

Archive an existing historical study in a separate local MLflow experiment:

```powershell
uv run --project tools/tracking --locked python tools/tracking/historical_export.py --study PATH_TO_STUDY --database artifacts/study-tracking/mlflow.db --tracking-artifacts artifacts/study-tracking/files --receipt artifacts/study-receipt.json
uv run --project tools/tracking --locked python tools/tracking/verify_historical_tracking.py PATH_TO_STUDY
```

The exporter stages a bounded copy, verifies the study manifest and full experiment
inventory, logs counts and all files, and compares every downloaded byte. Serial
replay reuses the finished run and repeats readback. Interrupted or duplicate exports
require inspection; concurrent exporters are not supported. Raw source data stays
local. This experiment records numerical historical studies, separately from model
research trajectories.

The recorded 45-case study passed readback for **64 files: 63 study artifacts plus
their manifest**, including 30,192 source observations and 7,516 backtest spans.
Real SQLite MLflow checks cover replay, stored-artifact corruption and source corruption.
