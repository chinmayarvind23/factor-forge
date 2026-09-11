# Commands

Run from the repository root. Install uv and Bun 1.3.10 and make them available on PATH.
The Python selection is pinned in `.python-version`; uv can provision Python when needed.

## Reproducible setup

```bash
uv sync --locked
bun install --cwd apps/web --frozen-lockfile --ignore-scripts
uv run python -m factorforge --help
uv run factorforge --version
```

The [local research operator](research-command.md) runs a reviewed saved plan through
the implemented research pipeline with PostgreSQL and local Ollama.

## Quality and build

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov --cov-fail-under=85
uv run pip-audit --skip-editable
uv build
bun run check
bun run test
bun run build
```

## Local API

Set `FACTORFORGE_MODE=local` in the server environment, then run:

```bash
uv run uvicorn factorforge.api.app:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

PowerShell: `$env:FACTORFORGE_MODE = 'local'`. POSIX shell: `export FACTORFORGE_MODE=local`.
Open `http://127.0.0.1:8001/docs` for the implemented OpenAPI contract.
The default local store is bounded and in memory; restarting the API removes its runs.
The only implemented transition is receipt to deterministic brief normalization.

## Durable storage and identity

For local durable runs, also set `FACTORFORGE_STORAGE=postgres` and `RDS_DSN` to a dedicated
database named `factorforge` or `factorforge_*`. Use an application role, not a superuser.
Startup initializes the `factorforge` and `factorforge_checkpoints` schemas. The driver
uses bounded connections and timeouts. PostgreSQL 16 is exercised in CI.

Run the same API command. `/ready` reports identity mode and storage separately. Durable
receipts and checkpoints survive restart; pending receipts are reconciled in bounded batches.
Do not point this setup at an unrelated shared database. No `.env` file is loaded implicitly.

For the authenticated API, set `FACTORFORGE_MODE=cognito`, `RDS_DSN`, `AWS_REGION`,
`COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID`. Configure Cognito resource scopes
`factorforge/create` and `factorforge/read`, and supply an access token in `Authorization: Bearer ...`.
`FACTORFORGE_ALLOWED_ORIGIN` sets one exact browser origin; `COGNITO_AUDIENCE` optionally
requires a resource-bound audience in addition to the access-token client check.
`FACTORFORGE_ENV` is a deployment label and never enables local identity.

Live Cognito and browser sign-in are not configured in the development evidence. The browser
currently targets the loopback API in local identity mode with either storage adapter.

Real database tests require a separate `FACTORFORGE_TEST_DSN` pointing to a dedicated
`factorforge_test_*` database. Tests never fall back to `RDS_DSN`; absent test storage is
reported as skipped locally, while CI provisions it explicitly. Run `uv run pytest tests/integration`.

## Local browser

With the API running, start the Next application in another terminal:

```bash
bun run dev
```

Open `http://127.0.0.1:3001`. Submit an idea and inspect its normalized brief and event history.
The browser preserves request identity after an uncertain network failure; a deliberate new
submission after success receives a new run ID.

For the production web build, run `bun run build` followed by `bun run --cwd apps/web start`.

## Browser verification

```bash
bun run --cwd apps/web playwright install chromium
bun run --cwd apps/web e2e
```

Both local servers must be running. Set `FACTORFORGE_E2E_OUTPUT` to a fresh output directory
to preserve screenshots, videos, traces and JSON results. Tests cover desktop/mobile submission
and an injected network failure followed by a retry against the real API.

## Reproduce the original data fixture

From the matching trusted checkout, create a local artifact directory and save the command's
JSON reference. In Bash:

```bash
mkdir -p artifacts/local
uv run --locked factorforge fixture-bundle --output artifacts/local/fixture-objects > artifacts/local/fixture-ref.json
uv run --locked factorforge verify-bundle --output artifacts/local/fixture-objects --ref artifacts/local/fixture-ref.json
```

In PowerShell, create the parent first with
`New-Item -ItemType Directory -Force artifacts/local | Out-Null`, then run the same two `uv`
commands. The reference reader supports UTF-8 and BOM-marked PowerShell encodings.

Replay returns `original_fixture`, the three formation-time security IDs and the three facts
known by 1 May 2024 at 20:00 UTC. Later amendments and the delayed filing remain in the saved
input but are excluded from that selection. No return or backtest metric is calculated.
The saved input and terms are sufficient after their checkout copies are removed; trusted
code, lock and installed environment still must match. Altered or missing evidence fails.

The separate [DVC tooling project](../tools/dvc/README.md) has a blocking dependency audit.
Its unavailable restoration test is an explicit skip in ordinary tests and a required check
in the complete release workflow. The original fixture can be inspected from Git without DVC.
Research orchestration, infrastructure and cloud commands will be documented when implemented.

Install scripts are disabled because this workspace currently requires none. The single web
package has its own lockfile. Root commands delegate by directory without creating workspace
symbolic links, which this Windows environment cannot traverse.

No command silently downloads a replacement benchmark dataset when a pinned snapshot is unavailable.

## Reproduce the literature retrieval pilot

```console
uv run --locked python -m factorforge.evaluation.cli --corpus data/literature/three-paper-pilot-v1/corpus.json --qrels data/literature/three-paper-pilot-v1/qrels.json --output artifacts/local/retrieval-pilot-v1 --k 3
```

This prints the per-query report and an immutable evaluation record reference. It uses the three
original summaries checked into Git and makes no network or model call. The record retains exact
inputs, ranking configuration, report, installed source snapshots and environment versions.
See the [pilot policy](../data/literature/three-paper-pilot-v1/README.md) for frozen input hashes,
separate metric denominators and the limits of this small development sample.

## Run one prepared source-extraction trial

The trial command requires your approved `SourcePacket` and `GoldCase` JSON files, a JSON
`ArtifactRef` for the frozen expected wire request, and an existing artifact store containing
the referenced page and request bytes. Full source papers are not distributed with the pilot.
Prepare and freeze these inputs before observing model output; the request comes from
`prepare_prompt` and the fixed provider profile described in the [contract](extraction-contract.md).

```console
uv run --locked python -m factorforge.evaluation.source_trial --packet packet.json --gold gold.json --expected-request expected-request.json --output artifacts/local/source-trial
```

It verifies the paper identity, PDF hash, selected page set and exact prepared request bytes
before one local Ollama call. Ollama must already serve the declared `llama3.1:8b` model at
`127.0.0.1:11434`; this command does not download models. Gold fields never enter the model prompt.
The command records a start before delivery and returns the extraction outcome, nine-field grade
and artifact pointers. It makes no retry and provides no automatic resume. An explicit rerun is
a new trial and must not replace a failed baseline attempt. Unexpected failures retain a safe
failure event when storage remains available; a storage outage can leave only the start record.

## Plan monthly targets from original source facts

The [monthly example](../data/fixtures/monthly-signals-v1/README.md) includes runnable source,
request and portfolio files. Run its command from a trusted checkout to produce conditional
targets. It archives exact inputs, installed source snapshots, package versions and a start
record before calculation. A terminal record links the assembly and targets, or preserves
the typed calculation failure. Exit status zero means target planning succeeded.

This command performs no model call, calendar admission, funding or trade execution. Stored
code is evidence only and is never executed for replay. Recompute using the matching trusted
code and verified stored input bytes. A storage failure can leave an incomplete start record.
