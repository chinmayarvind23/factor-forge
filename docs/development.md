# Development

Install the pinned Python environment with `uv sync --locked` and the browser dependencies
with `bun install --cwd apps/web --frozen-lockfile`.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -p no:tmpdir tests/unit
uv build
```

Database integration tests require `FACTORFORGE_TEST_DSN` pointing to a dedicated test
database. They do not fall back to the operator's database. Docker and LEAN checks need
the corresponding local runtimes. See `.github/workflows` for service provisioning and
required checks. Optional tools have separate locked environments and their own commands.

## Repository layout

| Path | Role |
|---|---|
| `src/factorforge/domain` | Typed source, strategy, account and workflow contracts |
| `src/factorforge/retrieval` | Discovery, source selection and structured extraction |
| `src/factorforge/orchestration` | Durable lifecycle, budgets, reports and research memory |
| `src/factorforge/backtests` | Execution, accounting and validation |
| `src/factorforge/sandbox` | Process and resource boundaries |
| `apps` | Browser application and static demonstration |
| `tools` | Optional operator integrations |
| `infra` | Runtime recipes and worker preparation |
| `tests`, `evals`, `data` | Checks, case definitions and authored test inputs |

Keep generated runs and reports in operator-selected output directories. Preserve test
fixtures and their expected values when refactoring arithmetic or timing behavior.
Dependency audits and image checks are part of the development workflow.
