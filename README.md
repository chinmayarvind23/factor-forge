# FactorForge

**Autonomous quantitative research with reproducible evidence**

Implementation status: browser/API research-brief flow with optional PostgreSQL storage and
actual LangGraph checkpoints. Submit an idea, set limits, inspect a stable run ID and recorded
normalization events, and recover after interrupted requests or API restarts in durable mode.
The API verifies Cognito access tokens and isolates runs by owner; live Cognito configuration
and browser sign-in remain pending. The research pipeline described below is
the target design and is not implemented yet. Benchmark metrics are unmeasured; see
[results](docs/results.md) for the evidence status and [commands](docs/commands.md) for runnable setup.

FactorForge turns a loose investment idea into a structured, reviewable research program. It retrieves relevant literature, extracts and proposes typed factor hypotheses, runs bounded experiments in sandboxes, validates strategies with time-series-aware statistics, independently verifies selected results in LEAN, records the full experiment lineage, and produces a research report that explains what worked, what failed, and why.

FactorForge is a research system. It does not place live trades or move capital.

## Core research loop

```mermaid
flowchart LR
    I[Research idea] --> L[Literature retrieval]
    L --> H[Typed hypotheses]
    H --> P[Research plan]
    P --> E[Sandboxed experiments]
    E --> V[Statistical validation]
    V --> C[Critic and decision]
    C -->|iterate| H
    C -->|promote| Q[LEAN verification]
    Q --> M[Research memory]
    M --> R[Research report]
```

LangGraph owns the durable state machine, budgets, stop conditions, retries, checkpoints, and legal transitions. Deep Agents handles bounded long-horizon work such as literature synthesis, hypothesis refinement, and critique. Deterministic code owns point-in-time rules, statistics, portfolio accounting, sandbox policy, and lineage validation.

## Architecture at a glance

```text
Browser on Vercel
        |
TypeScript + Bun
        |
       REST
        |
FastAPI control plane
        |
        +--> Cognito identity
        +--> LangGraph research state machine
        |       +--> Deep Agents bounded research workers
        |       +--> MCP tool adapters
        |       +--> checkpoint, permission, and budget gates
        |
        +--> RDS PostgreSQL: durable run state and lineage index
        +--> S3 + DVC: datasets, generated code, results, reports
        +--> Redis: ephemeral state, cache, rate limits, locks
        +--> Elasticsearch: literature and experiment search
        +--> Neo4j: derived research relationship graph
        +--> MLflow: experiments, registry, promotion metadata
        |
        +--> SQS: durable experiment jobs
                |
                v
        sandbox worker plane
        Docker locally, EKS Jobs in the cloud
                |
                +--> Polars fast research engine
                +--> PySpark offline scale path
                +--> LEAN verification over internal gRPC
                +--> R statistical cross-checks
                +--> RL environment + PyTorch / TRL trajectory learning and RLVR lab

Observability:
LangSmith + OpenTelemetry + Prometheus/Grafana + CloudWatch
```

The API workload is small compared with the research workload. Kubernetes exists for isolated, parallel, resource-bounded experiment jobs, not to decorate a low-traffic web API.

## Key features

- Natural-language idea to typed `FactorSpec`
- Literature retrieval with lexical, dense, and citation-graph signals
- Explicit plan, execute, verify research loop
- Point-in-time data contracts that make lookahead leakage testable
- Fast vectorized factor experiments with Polars
- Walk-forward and purged cross-validation with embargo
- Transaction-cost, turnover, drawdown, Sharpe, Sortino, IC, and HAC t-stat analysis
- Independent LEAN verification for promoted strategies
- Sandboxed generated code with no live-trading permissions
- Research memory across successful and failed experiments
- Reproducible lineage across prompts, data, code, configs, seeds, traces, and results
- Outcome and execution-path evaluation kept as separate scorecards
- LangSmith and OpenTelemetry traces for agent decisions, tools, latency, and cost
- MCP tool interoperability and an A2A cross-framework interoperability path
- Offline PyTorch/TRL learning from verified research trajectories
- RL environment with typed states/actions, verifiable rewards, RLVR, and benchmarked multi-step agentic RL

## Research pipeline canon

The research lifecycle explicitly implements the nine-stage autonomous-research sequence:

```text
Evaluation Harness
Hypothesis Generator
Literature Retrieval
Experiment Runner
Result Evaluator
Paper Writer
Critic Loop
Iteration Scheduler
End-to-End Research Demo
```

See [docs/research-pipeline.md](docs/research-pipeline.md).

The post-MVP learning path adds a versioned research environment, successful and failed trajectory datasets, preference learning, RLVR with deterministic/reference-based rewards, and multi-step agentic RL. The learned policy remains inside the same hard harness boundaries. See [docs/agentic-rl.md](docs/agentic-rl.md).

Documentation

- [Product requirements](PRD.md)
- [System design](docs/system-design.md)
- [High-level design](docs/HLD.md)
- [Low-level design](docs/LLD.md)
- [Architecture alternatives](docs/architecture-alternatives.md)
- [API contracts](docs/api-contracts.md)
- [Data model and lineage](docs/data-and-lineage.md)
- [Quant methodology](docs/quant-methodology.md)
- [Research pipeline](docs/research-pipeline.md)
- [Agentic RL and RLVR](docs/agentic-rl.md)
- [Agent harness](docs/harness.md)
- [Research memory and failed-experiment ledger](docs/research-memory.md)
- [Evaluation methodology](docs/evaluation.md)
- [Benchmark methodology](docs/benchmark-methodology.md)
- [Security](docs/security.md)
- [Threat model](docs/threat-model.md)
- [Observability](docs/observability.md)
- [Performance and scalability](docs/performance.md)
- [Failure modes](docs/failure-modes.md)
- [Deployment](docs/deployment.md)
- [Interoperability](docs/interoperability.md)
- [Reproducibility](docs/reproducibility.md)
- [Quality gates](docs/quality-gates.md)
- [Results](docs/results.md)
- [Demo plan](docs/demo.md)
- [Technical blog outline](docs/blog-outline.md)
- [Commands](docs/commands.md)
- [References](docs/references.md)
- [Architecture decision records](docs/adr/)

## Repository shape

```text
apps/
  api/
  web/
src/factorforge/
  api/
  auth/
  domain/
  orchestration/
  agents/
  tools/
  retrieval/
  data/
  factors/
  backtests/
  validation/
  memory/
  lineage/
  sandbox/
  telemetry/
  interop/
tests/
evals/
benchmarks/
data/
research/
artifacts/
infra/
monitoring/
scripts/
docs/
```

The tree grows as components are implemented. Stable module boundaries are planned up front, but a directory does not justify creating unused abstractions.

## First useful path

Local development starts with the smallest end-to-end research loop:

```text
idea -> typed hypothesis -> tiny fixture dataset -> Polars backtest
     -> deterministic validation -> research verdict -> report
```

Cloud infrastructure, distributed workers, additional search systems, A2A, RL environments, RLVR, agentic RL, and large-scale data paths are added after this loop is correct and measurable.

See [docs/commands.md](docs/commands.md) for the intended command surface.
