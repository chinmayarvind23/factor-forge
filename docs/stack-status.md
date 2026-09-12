# Technology roles and implementation status

The core research workflow, optional training tools and deployment paths have different
runtime requirements. A technology listed in the architecture is not automatically a
deployed service. This map describes the current code and retained execution evidence.

| Technology | Product role | Current implementation and evidence |
|---|---|---|
| Python | Typed research contracts, execution and validation | [Core package](../src/factorforge/), exercised research and historical-study paths |
| LangGraph | Durable workflow transitions and resume | [Orchestration](../src/factorforge/orchestration/), PostgreSQL checkpoints |
| Deep Agents | Bounded investment-idea planning | [Planner](../tools/planning/README.md), retained local model planning execution |
| Polars | Historical panel processing and deterministic numerical research | [Study](../src/factorforge/evaluation/historical_study.py), 30,192 input rows |
| PySpark | Optional offline monthly panel materialization | [Spark SQL job](../tools/spark/README.md), actual Spark 4.0.1 run: 30,192 daily rows to 1,440 monthly rows with readback; optional 4.2 environment unexecuted |
| LEAN / C# / gRPC | Independent execution and accounting comparison | [LEAN integration](../infra/lean/execution/README.md), actual reference fills and valuations |
| PostgreSQL | Research state, budgets, idempotency and operation receipts | [PostgreSQL stores](../src/factorforge/orchestration/), exercised local database paths |
| SQS | Optional asynchronous research delivery | [FIFO adapter](sqs-research.md), offline acknowledgement checks; AWS execution unmeasured |
| Redis | Expiring literature-discovery artifact locators | [Cache integration](../tools/cache/README.md), five offline checks and real Redis 7.4.11 reuse/expiry/fallback verification |
| Elasticsearch | BM25 literature metadata index and DOI lookup | [Search CLI](../tools/search/README.md), verified capture replay before indexing; optional service |
| Kafka | Archived raw-quote transport and replay | [Producer/consumer](../tools/streaming/README.md), source admission, deterministic keys and durable deduplication before offset commit |
| Prometheus / Grafana | Retained evidence metrics and scrape health | [Provisioned local dashboard](../tools/observability/README.md), actual Grafana 12.1.0 dashboard and Prometheus gauge readback |
| GraphQL | Read-only saved research evidence queries | [Explorer](../tools/explorer/README.md), bounded Strawberry schema and HTTP request checks |
| MCP | Read-only evidence tools for MCP clients | [Official SDK stdio server](../tools/explorer/README.md), shared evidence loader and protocol checks |
| Docker | Resource-limited experiment and LEAN execution | [Sandbox](sandbox.md), [LEAN runtime](../infra/lean/) |
| MLflow | Verified research and historical experiment artifacts | [Tracking tools](../tools/tracking/README.md), actual SQLite readback and replay |
| Neo4j | Research lineage projection and reverse lookup | [Graph projection](../tools/tracking/NEO4J.md), real-server import/readback evidence |
| OpenTelemetry | Operation and backtest spans | Historical study retained 7,516 SDK spans |
| LangSmith | Retrospective research trace import | [SDK/HTTP adapter](../tools/tracking/LANGSMITH.md); hosted-account readback remains unverified |
| PyTorch / TRL / PEFT | Reviewed SFT and preference-training candidates | [Local LoRA trainer](../tools/training/README.md); code and lock implemented, optimizer execution unmeasured |
| AWS / boto3 | Optional S3 artifacts and Cognito authentication | [S3 adapter](../src/factorforge/data/s3_artifacts.py), [Cognito adapter](../src/factorforge/auth/cognito.py), [setup](deployment.md); no AWS deployment claimed |
| Hugging Face | Free public evidence dashboard | [Live Space](https://huggingface.co/spaces/chinmayarvind/factorforge), static saved-result explorer |
| FastAPI / Next.js / TypeScript | Application API and local web interface | [API and UI contracts](api-contracts.md), [web app](../apps/web/); separate from static Space |
| DVC | Optional dataset restoration/versioning | [Isolated tooling](../tools/dvc/README.md); dependency advisory gate retained, current execution blocked |

## Scale and platform roadmap

The broader architecture also names Weaviate, CloudWatch, A2A/Google ADK
and optional Supabase.
These are planned scale, retrieval, interoperability or platform roles; they are not
represented as completed services in the current product. Polars handles the measured
dataset and PostgreSQL handles the implemented durable workflow. Adding an unused
dependency would not establish those planned integrations.

The optional search, streaming, explorer and dashboard integrations have local setup
commands and separate verification receipts. They are not hosted on the static Hugging
Face Space. Elasticsearch currently implements BM25 metadata retrieval; dense hybrid
ranking remains future work. Kafka replay is an archived-data transport, not a live feed.

Terraform/EKS/Kubernetes workers, ECR, EC2 and Lightsail remain optional infrastructure
designs under the free-hosting delivery scope. The public Space runs no worker cluster
or training job. Distributed processing, additional service integrations and learned
policy promotion require their own implementation and verification work.
