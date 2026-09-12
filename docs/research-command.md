# Local research operator

For optional asynchronous operator execution, see [SQS research delivery](sqs-research.md).

## Complete a resumable workflow

```powershell
uv run factorforge-research --request research-request.json --artifacts artifacts/research --workflow
uv run factorforge-research --artifacts artifacts/research --memory-query "momentum"
```

`--workflow` connects research execution, verified report publication and searchable
outcome memory in a PostgreSQL-checkpointed LangGraph. It includes report export and
preserves the existing three stdout receipt formats. All three plan versions work.
The full brief, plan and captured evaluation clock remain part of the stable identity.

The research node retains a canonical result and budget receipt before advancing.
After that receipt exists, restart recovers the entire research stage without entering
its scheduler or calling models/backtests again. Report and memory publication resume
from their own checkpoints. Earlier provider crashes retain the existing pending-operation
reconciliation rule. Completion verifies the request/result/budget/report artifact closure.

`--memory-query` performs a bounded literal search of the operator's saved research ideas
and returns completion references for inspection. It includes completed, held and stopped
candidate outcomes. These are reusable evidence locators, not automatic factor promotion
or an evaluated learned-memory policy. Direct database and local artifact access remain
trusted operator capabilities. Existing commands without `--workflow` retain their behavior.

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

Use `--direction-revision` during preparation for version-three scheduling. This implies
direction review and permits one additional source-reading attempt per conflicting
candidate. If the revision supports the reviewed direction, a separately retained
amendment can proceed to monthly execution. The prepared plan reserves up to one
additional USD for revision; all three model calls remain subject to the original
brief budget and deadline. Local dollar cost remains unknown. Use a new request path.

The recorded development trial reached extraction, compilation and monthly execution.
Its model reversed the source's long/short direction; the borrow-availability rule
stopped execution and retained that outcome. All 49 reachable artifact references
passed independent size/hash verification. Replay returned the same result and
unchanged two-operation budget ledger. This is live integration and recovery
evidence, not a successful factor reproduction or an extraction-accuracy benchmark.

A subsequent version-two live trial caught the direction disagreement before monthly
dispatch. Extraction returned `long_low_short_high`; the source-only review returned
`long_high_short_low` with an exact source quote. The final inventory retained
`DIRECTION_REVIEW_DISAGREEMENT`, both observations and no experiment dispatch. All
27 reachable artifact references passed size/hash checks. Replay returned the same
result and unchanged two-model-operation ledger. This is one original-source gate
trial, not a measured improvement on the published-factor benchmark.

The first version-three live trial retained a revision whose proposed quote changed
the source's direction wording. Exact quote verification classified it as invalid,
so no amended experiment was dispatched. The run retained all three model attempts
and `DIRECTION_AMENDMENT_REVISION_INVALID`. All 33 reachable artifact references
verified, and replay preserved the final result and three-operation ledger. This
trial is the frozen revision baseline; accepted amendments have been exercised with
controlled observations and the real monthly accounting engine.

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

After execution, use the result reference with the [offline report exporter](research-reports.md)
to read candidate outcomes, direction judgments and linked evidence. Reporting consumes
no additional model calls or experiment budget and supports all three saved plan versions.

## Publish the report with the operator

```powershell
uv run factorforge-research --request research-request.json --artifacts artifacts/research --report
```

`--report` preserves the existing request identity and the first two stdout receipts.
After result publication it exports the same verified JSON/Markdown report as the
offline command, snapshots the settled operation ledger and publishes a
`research-completion-v1` receipt binding run ID, full request, result, ledger, report
and Markdown. A third stdout line identifies the completion artifact and local report.
The flag adds no model calls or experiment operations; it can be used when replaying
an already settled request.

If report export stops, the result receipt remains available. Retry the same command
to recover existing operations and finish publication. A differing file at the report's
content-derived export path is rejected without overwriting it. Report publication
completion is not a factor-promotion decision or a release benchmark grade.
