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

The CLI currently provides help and version information. Research, evaluation, reproduction,
local infrastructure and cloud commands will be documented here when implemented and verified.

Install scripts are disabled because this workspace currently requires none. The single web
package has its own lockfile. Root commands delegate by directory without creating workspace
symbolic links, which this Windows environment cannot traverse.

No command silently downloads a replacement benchmark dataset when a pinned snapshot is unavailable.
