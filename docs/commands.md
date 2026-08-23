# Commands

These are intended stable command shapes. Exact dependencies are added when the corresponding implementation exists.

## Python

```bash
uv sync
uv run python -m factorforge --help
```

## Web

```bash
cd apps/web
bun install
bun run dev
```

## API

```bash
uv run uvicorn factorforge.api.app:app --reload
```

## Quality

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Evals

```bash
uv run factorforge eval smoke
uv run factorforge eval benchmark --suite benchmark-v1
```

## Research

```bash
uv run factorforge research run \
  --idea "residual momentum after sector neutralization" \
  --max-experiments 8 \
  --budget-usd 5
```

## Reproduce one case

```bash
uv run factorforge reproduce --manifest artifacts/benchmark/<case>/manifest.json
```

## Local infrastructure

```bash
docker compose up -d
```

## Terraform

```bash
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan
```

## Kubernetes

```bash
kubectl apply --dry-run=server -f infra/k8s/
```

## DVC

```bash
dvc status
dvc pull
```

## MLflow

```bash
mlflow server
```

No command silently downloads a different benchmark dataset when a pinned snapshot is unavailable.
