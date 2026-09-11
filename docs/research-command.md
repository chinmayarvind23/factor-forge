# Local research operator

The `factorforge-research` command runs the implemented retrieval, extraction,
strategy compilation, monthly execution and requested HAC pipeline against PostgreSQL.
It uses the fixed trusted operator identity `factorforge-operator/local-worker`.
This is a local process with direct database credentials, not a browser authentication
mechanism. Browser principals keep their existing capabilities.

## Prepare the original integration example

```powershell
uv run python infra/research/prepare_original.py --artifacts artifacts/research-original --request artifacts/research-original/request.json
uv run factorforge-research --request artifacts/research-original/request.json --artifacts artifacts/research-original
```

Set `RDS_DSN` first and make the fixed local Ollama model available as described in
the provider setup. Preparation reads only the original source passage and input
data, captures evaluation time once and refuses to overwrite the saved request.
It never supplies expected backtest outputs to the pipeline. Replay uses the
second command with the same request. This original plaintext source is represented
as page one of the integration fixture; it is not a retrieved published paper.
Model observations remain unedited even if they require further strategy review.

Add `--direction-review` to the preparation command to create a version-two plan
that checks a separate source-cited direction judgment before scheduling each compiled
candidate. Use a new request path and preserve it for replay. The review reserves an
additional maximum allowance of one USD per selected compiled candidate; actual local
model dollar cost remains unknown. A disagreement retains both observations and holds
the candidate without dispatching its monthly experiment.

The recorded development trial reached extraction, compilation and monthly execution.
Its model reversed the source's long/short direction; the borrow-availability rule
stopped execution and retained that outcome. All 49 reachable artifact references
passed independent size/hash verification. Replay returned the same result and
unchanged two-operation budget ledger. This is live integration and recovery
evidence, not a successful factor reproduction or an extraction-accuracy benchmark.

## Supply a reviewed request

Prepare a UTF-8 JSON file matching `orchestration.command.OperatorRequest`:

```python
from pathlib import Path
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.command import OperatorRequest
from factorforge.orchestration.research_experiments import ExperimentPlan

plan = ExperimentPlan.model_validate_json(Path("reviewed-plan.json").read_bytes())
request = OperatorRequest(
    brief=ResearchBrief(idea="Your research idea", max_experiments=3),
    plan=plan,
)
Path("research-request.json").write_bytes(request.canonical_bytes())
```

The plan must contain the reviewed source catalog, exact execution bindings,
starting capital, captured evaluation time and source allowance described in
[experiment scheduling](research-experiments.md). Populate the artifact directory
with every referenced source page and dataset object first. This command does not
acquire data rights or substitute missing data. The current monthly execution
profile uses original fixtures. Extraction uses the existing local Ollama profile.

Set `RDS_DSN` through your local environment and run:

```powershell
uv run factorforge-research --request research-request.json --artifacts artifacts/research
```

The module entrypoint also works before reinstalling console scripts:

```powershell
uv run python -m factorforge.orchestration.command --request research-request.json --artifacts artifacts/research
```

The database must satisfy the existing dedicated FactorForge database guard. The
default schema is `factorforge`; `--schema` supports the store's existing bounded
application/test schema names. The command neither creates a PostgreSQL server nor
prints credentials. Request input is capped at four MiB and validated before setup.

Stdout contains two JSON lines: the run ID and retained request reference, then
the same run ID and final research-result reference. Errors use safe JSON on stderr.
Exit zero means a final pipeline inventory was published; inspect its candidate
and experiment outcomes to distinguish completed, skipped and budget-stopped work.
It is not an autonomous benchmark grade or a factor-promotion decision.

The canonical complete request determines idempotency. Retry with the same request,
database schema and artifact directory to resume/recover prior work. Preserve the
captured evaluation clock. Changing the request creates a distinct operator run
with its own brief budget; this should be an intentional new research request.
Pending reservations still require reconciliation rather than repeated execution.
