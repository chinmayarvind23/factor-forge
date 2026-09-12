# Deployment

## Local research and application

The research command needs PostgreSQL, Ollama and persistent artifact storage. Follow
[research setup](research.md) first. For the local API:

```powershell
$env:FACTORFORGE_MODE = 'local'
uv run uvicorn factorforge.api.app:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

Open http://127.0.0.1:8001/docs for the API contract. To retain API state in PostgreSQL,
set `FACTORFORGE_STORAGE=postgres` and `RDS_DSN` for a dedicated FactorForge database.
The default in-memory API store is process-local.

Install the browser workspace with `bun install --cwd apps/web --frozen-lockfile` and
follow its package scripts. Configure the API origin for the environment you run.

## Supporting services

- [GraphQL / MCP](../tools/explorer/README.md)
- [Elasticsearch](../tools/search/README.md)
- [Redis](../tools/cache/README.md)
- [Kafka](../tools/streaming/README.md)
- [Grafana / Prometheus](../tools/observability/README.md)
- [MLflow](../tools/tracking/README.md), [Neo4j](../tools/tracking/NEO4J.md), [LangSmith](../tools/tracking/LANGSMITH.md)
- [PySpark](../tools/spark/README.md), [training](../tools/training/README.md), [DVC](../tools/dvc/README.md)

These tools have separate environments and operator-owned storage. Keep their local
listeners private and use the authentication configuration appropriate to your host.

## Static Hugging Face demo

```powershell
uv run python scripts/build_space.py
uv run python -m http.server 8766 --bind 127.0.0.1 --directory dist/space
```

Review the generated directory before publishing. Use a static Space and upload only
that directory with the Hugging Face CLI. It displays saved material; Python research
execution runs separately. The [demo guide](demo.md) includes the hosted link and recording.

## AWS configuration

For an operator-managed deployment, provide private PostgreSQL connectivity and persistent
artifact storage. The [S3 adapter](../src/factorforge/data/s3_artifacts.py) and
[Cognito identity adapter](../src/factorforge/auth/cognito.py) expose their configuration
through the application interfaces.

Cognito mode uses `FACTORFORGE_MODE=cognito`, `AWS_REGION`, `COGNITO_USER_POOL_ID`,
`COGNITO_CLIENT_ID` and `RDS_DSN`. Configure the expected application scopes and exact
allowed browser origin. Put the API behind HTTPS and keep the worker's Docker socket
inaccessible from the network. Use the [SQS adapter](../src/factorforge/orchestration/sqs_jobs.py)
when asynchronous operator delivery is required.

Provision infrastructure under your own account policies, with restricted IAM, secret
storage, budget controls and a tested database/artifact restore procedure. These setup
instructions do not deploy resources automatically.
