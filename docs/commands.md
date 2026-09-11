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

The current CLI provides help and version information. The web build verifies the TypeScript
workspace. API serving, browser run submission, research, evaluation, reproduction, local
infrastructure and cloud commands will be documented here when implemented and verified.

Install scripts are disabled because this workspace currently requires none. The single web
package has its own lockfile. Root commands delegate by directory without creating workspace
symbolic links, which this Windows environment cannot traverse.

No command silently downloads a replacement benchmark dataset when a pinned snapshot is unavailable.
