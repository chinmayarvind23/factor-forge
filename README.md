# FactorForge

**Turn investment ideas into structured, repeatable research.**

FactorForge helps quantitative researchers move from a question and supporting papers
to an explicit strategy, a controlled experiment and an inspectable research decision.
It brings source selection, model interpretation, execution rules and research memory
into one workflow, so the reasoning behind a strategy stays connected to its inputs.

[Open the demo](https://huggingface.co/spaces/chinmayarvind/factorforge) ·
[Documentation](docs/index.md) · [Run research](docs/research.md)

![FactorForge research journey](docs/assets/research-journey.gif)

[Watch the recording](docs/assets/research-journey.mp4). The demonstration follows a
recorded research journey through source selection, extraction, strategy compilation
and an execution decision. It uses authored example inputs and saved model output.

## Why it matters

Investment research spans papers, data transformations, strategy definitions and
backtests. When those steps live in separate notebooks and conversations, assumptions
are difficult to trace and work is difficult to resume. FactorForge preserves that
context and makes execution policy explicit throughout the research process.

## Key features

- **Source-grounded research:** discover literature, admit reviewed source pages and
  preserve citations alongside structured model interpretations.
- **Strategy construction:** compile typed hypotheses and combine compatible source
  strategies using explicit weights and shared execution assumptions.
- **Controlled experiments:** enforce point-in-time data access, costs, funding rules,
  corporate actions and process boundaries before accepting an execution outcome.
- **Durable workflows:** resume research with PostgreSQL-backed LangGraph checkpoints,
  bounded operation budgets and stable request identities.
- **Research memory:** retain source artifacts, prompts, model responses, code and
  decisions for inspection, report export and subsequent research.
- **Operator tools:** search literature with Elasticsearch, read evidence through
  GraphQL or MCP, replay archived quotes through Kafka and inspect Grafana dashboards.

## Setup

Install Python as selected by `.python-version`, uv, PostgreSQL and Ollama. From the
repository root:

```powershell
uv sync --locked
$env:RDS_DSN = 'postgresql://USER:PASSWORD@localhost:5432/factorforge'
ollama pull llama3.1:8b
```

Use a dedicated database and provide credentials through your local environment.
[The operator guide](docs/research.md) explains provider selection and service setup.

## Run an example

Prepare an authored source example and run its saved request:

```powershell
uv run python infra/research/prepare_original.py --artifacts artifacts/research-original --request artifacts/research-original/request.json
uv run factorforge-research --request artifacts/research-original/request.json --artifacts artifacts/research-original --workflow
```

The command retains the research decision and its artifacts. Reuse the saved request
to resume the same workflow. For your own papers, follow [source and data preparation](docs/data.md).

To inspect the local dashboard without a model or database:

```powershell
uv run python scripts/build_space.py
uv run python -m http.server 8766 --bind 127.0.0.1 --directory dist/space
```

Open http://127.0.0.1:8766. The builder executes authored examples and writes its output
under `dist/space`; the hosted demo displays saved material.

## How it works

```mermaid
flowchart LR
    Idea[Research idea] --> Sources[Reviewed literature and data]
    Sources --> Model[Structured interpretation]
    Model --> Strategy[Strategy compilation and review]
    Strategy --> Experiment[Controlled experiment]
    Experiment --> Decision[Research decision]
    Decision --> Memory[Reports and research memory]
    Sources & Model & Strategy & Experiment --> Artifacts[Content-addressed artifacts]
    Artifacts --> Tools[Inspection and tracking tools]
```

LangGraph coordinates the research lifecycle. Deterministic Python code controls data
admission, accounting, execution and validation. A model can propose a strategy; it
cannot change the run's permissions, data timing or resource budget.

## Technology

**Python · FastAPI · LangGraph · Polars · LEAN · PostgreSQL · Docker**

Python and FastAPI expose the research service, LangGraph coordinates research workflows,
and Polars prepares data for deterministic strategy execution. LEAN provides independent
reference-backtest verification, while Docker isolates experiment processes. PostgreSQL
retains workflow checkpoints and the operation ledger; content-addressed filesystem storage
preserves research artifacts for inspection and replay. Ollama supplies local model inference.

### Integrations

Configure the integrations your deployment needs:

- **Research and data:** Deep Agents for bounded planning, Elasticsearch for literature
  metadata search, Redis for discovery caches and PySpark for panel-data materialization.
- **Memory and tracking:** MLflow for experiment artifacts, Neo4j for research-memory
  projections and LangSmith for importing recorded research-operation traces. OpenTelemetry
  supports execution tracing; Prometheus and Grafana expose operational monitoring.
- **Interfaces and delivery:** GraphQL and MCP for read-only research inspection, Kafka
  for archived quote-event transport, and Next.js and TypeScript for the application UI.
  Hugging Face hosts the static research demo.
- **Learning and versioning:** PyTorch, TRL and PEFT for trajectory-based training tools,
  with DVC for data-versioning workflows.
- **AWS adapters:** S3 for artifact storage, SQS for asynchronous job delivery and Cognito
  for application identity in operator-managed deployments.

See [architecture](docs/architecture.md) for component boundaries and
[deployment setup](docs/deployment.md) for integration guides and configuration.

## Development

```powershell
uv run ruff check .
uv run pytest -p no:tmpdir tests/unit
uv build
```

See [development](docs/development.md) for integration services and browser tooling.

## Design directions

Further work can make source review easier, broaden data-provider coverage and improve
worker scheduling as workloads grow. The architecture keeps model proposals separate
from execution policy so these changes can be introduced without weakening accounting,
source provenance or authorization. [Architecture](docs/architecture.md) explains the tradeoffs.
