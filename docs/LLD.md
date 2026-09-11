# FactorForge Low-Level Design

Implemented local slice: `domain/research_brief.py` validates immutable requests and records;
`orchestration/local_runs.py` serializes idempotent creation with a lock, caps the store at 1000
runs, and records a single normalization transition. `api/app.py` enforces explicit local mode,
loopback peer/host and exact browser Origin before operations. `api/body_limit.py` caps raw JSON
bodies at 16 KiB including chunked uploads. This API flow calls no model and performs no backtest.
The stored original request determines idempotency equality, so differences in internal
whitespace conflict even when deterministic normalization would produce the same brief.
The Next.js console keeps an idempotency key with an uncertain submission until the API
accepts it. Polling reads canonical API events sequentially and stops at normalization,
an error, or its attempt limit. It validates response shapes and never invents progress.
The broader modules and state machine below describe the target system.

The independent literature path uses `domain/literature.py` and `retrieval/lexical.py` for
immutable documents and bounded BM25 ranking. `evaluation/retrieval.py` requires complete binary
judgments and separates answerable and no-relevant query denominators; its CLI archives the
input bytes and actual result. `providers/ollama.py` supplies fixed, versioned loopback profiles
with no tools, retries, endpoint redirection or inferred dollar cost. `retrieval/extraction.py`
retains raw source pages, a versioned whitespace transform, prepared prompt and provider record.
`domain/extraction.py` validates observations without treating parsing as accuracy, while
`domain/formula.py` interprets a closed arithmetic grammar without executing Python. See the
[extraction contract](extraction-contract.md) and [formula language](formula-language.md).

The durable adapter uses owner issuer/subject predicates and SQL uniqueness for idempotency.
Dollar values use fixed two-decimal canonical serialization, preserving equality between
`5`, `5.0` and `5.00`. Run creation and its first event commit together. An actual LangGraph
PostgresSaver persists execution before the adapter publishes the normalized state and event
in a second canonical transaction. A checked checkpoint can repair a lost publication.
Short row locks are suitable for this pure normalization step; later model calls require a
durable lease/worker protocol. API blocking work has eight admission slots and rejects overload.

The token verifier accepts only fixed-pool RS256 access tokens. It requires issuer, subject,
expiry, issue time, client and token-use claims; only configured scopes grant capabilities.
Its signing-key cache holds up to 16 keys for 300 seconds, refreshes at most once per 30 seconds,
and bounds raw responses to 64 KiB. HTTP operations have three-second timeouts with an elapsed
stream check at five seconds; this is not an exact preemptive total deadline. Fresh cached
keys may work during provider outage, but expired keys never bypass refresh failure.

`domain/artifacts.py` defines strict location-free content references. `data/artifacts.py` uses
digest-derived names, pinned filesystem ancestors and no-overwrite atomic publication;
`data/s3_artifacts.py` verifies conditional uploads and bounded checksum-enabled reads.
`domain/datasets.py` canonicalizes immutable provenance, coverage, policy and use-rights metadata.
`data/catalog.py` reuses the bounded PostgreSQL pool and migration-owned `dataset_versions`
table. Owner issuer/subject plus version identify publications; sharing needs a separate
capability. Byte verification precedes the transaction, and retention is rechecked before
commit or return. Orphan object cleanup and ingestion HTTP endpoints are not implemented.
`data/point_in_time.py` selects known facts and historical membership using absolute UTC time.
Conflicting eligible history fails before selection; later filings do not rewrite earlier
formations. Units and duration contexts remain separate, with no implicit conversion.

## 1. Domain modules

```text
src/factorforge/
  domain/
    research_brief.py
    factor_spec.py
    experiment.py
    result.py
    verdict.py
    lineage.py
  orchestration/
    graph.py
    state.py
    transitions.py
    budgets.py
    checkpoints.py
    scheduler.py
  agents/
    literature.py
    hypothesis.py
    critic.py
    report.py
    skills/
  tools/
    registry.py
    contracts.py
    literature.py
    data_catalog.py
    backtest.py
    stats.py
    memory.py
  retrieval/
    elastic.py
    neo4j.py
    weaviate_lab.py
    fusion.py
  data/
    catalog.py
    point_in_time.py
    snapshots.py
    corporate_actions.py
  factors/
    parser.py
    compiler.py
    transformations.py
  backtests/
    polars_engine.py
    accounting.py
    costs.py
    lean_client.py
  validation/
    walk_forward.py
    purged_cv.py
    hac.py
    bootstrap.py
    multiple_testing.py
    r_crosscheck.py
  memory/
    canonical.py
    graph_projection.py
    retrieval.py
  lineage/
    manifest.py
    hashes.py
    evidence.py
  sandbox/
    spec.py
    local_docker.py
    k8s_job.py
    policy.py
  telemetry/
    traces.py
    metrics.py
    costs.py
  interop/
    mcp/
    a2a/
  learning/
    environment.py
    observations.py
    actions.py
    rewards.py
    trajectories.py
    trainers.py
    policy_adapter.py
```

Modules are created when their implementation starts. The layout describes ownership, not a requirement to create empty abstractions.

## 2. Core schemas

```python
class ResearchBrief(BaseModel):
    run_id: UUID
    question: str
    asset_class: Literal["US_EQUITY"]
    universe_hint: str | None
    horizon: str | None
    constraints: list[str]
    max_llm_cost_usd: Decimal
    max_wall_time_s: int
    max_experiments: int
```

```python
class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    mechanism: str
    expected_direction: Literal["positive", "negative", "conditional"]
    variables: list[str]
    metric: str
    baseline_ref: str | None
    source_refs: list[str]
    novelty_score: float
    specificity_score: float
    testability_score: float
```

```python
class ExperimentSpec(BaseModel):
    experiment_id: str
    run_id: UUID
    hypothesis_id: str
    factor_spec_version: str
    dataset_version: str
    engine: Literal["polars", "lean", "spark", "r"]
    code_sha256: str
    config: dict[str, JsonValue]
    seeds: list[int]
    timeout_s: int
    memory_mb: int
    cpu_limit: float
    network_policy: Literal["none", "approved_only"]
    required_metrics: list[str]
    idempotency_key: str
```

```python
class ResearchVerdict(BaseModel):
    hypothesis_id: str
    status: Literal[
        "supported",
        "unsupported",
        "unstable",
        "inconclusive",
        "invalid_data",
        "invalid_method",
        "verification_disagreement",
    ]
    evidence_refs: list[str]
    limitations: list[str]
    next_actions: list[str]
```

## 3. State machine

```text
RECEIVED
  -> BRIEF_NORMALIZED
  -> LITERATURE_READY
  -> HYPOTHESES_READY
  -> PLAN_READY
  -> EXPERIMENTS_RUNNING
  -> VALIDATION_RUNNING
  -> CRITIQUE_READY
      -> PLAN_READY       if another bounded iteration is justified
      -> LEAN_VERIFYING   if a result is promoted
      -> REPORT_READY     if no LEAN verification is required
  -> REPORT_READY
  -> COMPLETED
```

Every transition is a policy function over current state plus verified event.

## 4. Budget gate

```python
def can_start_step(
    *,
    remaining_usd: Decimal,
    remaining_seconds: int,
    remaining_experiments: int,
    estimate: StepEstimate,
) -> bool:
    return (
        remaining_usd >= estimate.max_cost_usd
        and remaining_seconds >= estimate.max_wall_time_s
        and remaining_experiments >= estimate.experiment_slots
    )
```

The model never decides whether a hard budget can be exceeded.

## 5. Tool contract

Each tool declares:

```text
name
version
description
input schema
output schema
required capability
network policy
data classification
idempotency behavior
retry class
timeout
failure codes
telemetry attributes
```

Tool descriptions remain short and non-overlapping.

## 6. Literature retrieval

Candidate path:

```text
BM25 / lexical -> top N
dense retrieval -> top N
citation-neighborhood expansion -> top N
dedup by stable paper id
feature construction
rerank/fusion
```

Initial fusion experiment:

```text
score =
    w_lexical * normalized_bm25
  + w_dense * normalized_dense
  + w_graph * citation_proximity
  + w_recency * recency
```

The final method is selected by qrels and ablation.

## 7. Hypothesis queue

Generate multiple hypotheses before expensive experiments.

```text
rank =
    0.4 * novelty
  + 0.3 * specificity
  + 0.3 * testability
```

These weights are configuration. The benchmark can replace them.

Near duplicates use cosine distance over normalized embeddings:

```text
distance(a, b) = 1 - dot(a, b)
```

## 8. Scheduler

```text
UCB_i = mean_reward_i + c * sqrt(ln(N) / n_i)
```

Pruning is separate:

```text
if n_i >= min_trials and mean_reward_i < floor:
    prune(branch_i)
```

Hard stop conditions include max experiments, wall time, LLM dollars, no executable hypotheses, unrecoverable security/data error, and user cancellation.

## 9. Backtest accounting

```text
raw signal
-> lag by availability rule
-> eligibility mask
-> winsorize / standardize
-> neutralize if specified
-> form portfolio weights
-> apply turnover and transaction costs
-> compute returns
-> aggregate metrics
```

No LLM performs return accounting.

## 10. LEAN verifier

LEAN runs through a separate service boundary because it has its own runtime and engine semantics and promoted strategies need independent implementation.

```text
VerifyStrategy(LeanVerificationRequest) -> LeanVerificationResult
Health(HealthRequest) -> HealthResponse
Capabilities(CapabilitiesRequest) -> CapabilitiesResponse
```

## 11. Lineage manifest

Every run records:

```text
run_id
git_sha
factor_spec_id + version
dataset_dvc_hash
dataset_content_hashes
provider snapshot ids
generated_code_hash
environment/container digest
random seeds
orchestrator version
prompt versions
model ids
tool versions
retrieval config
experiment ids
MLflow run ids
LangSmith trace ids
OTel trace ids
LEAN engine version
metric implementation version
cost/pricing snapshot
created_at
```

## 12. Error model

```text
InputError
AuthorizationError
DataContractError
LeakageDetectedError
ToolValidationError
SandboxPolicyError
ExperimentTimeoutError
ExperimentOOMError
DependencyUnavailableError
BudgetExhaustedError
VerificationDisagreementError
LineageIncompleteError
```

Typed failures enter evals and observability directly.

## 13. Context management

Each model call receives current state summary, relevant literature, selected prior memory, active FactorSpec, step contract, allowed tool descriptions, and failure feedback. The full transcript is not blindly appended.

## 14. Peer-agent communication

A subagent output is parsed into a typed result object. It is never directly executed as an instruction.

## 15. Comments

Application comments explain non-obvious invariants such as point-in-time timing, sandbox boundaries, retry semantics, or numerical assumptions. Architecture rationale belongs in ADRs and design docs. Comment on each function to explain it.

## 16. RL environment contracts

### ResearchAction

```python
class ResearchAction(BaseModel):
    kind: Literal[
        "search_literature",
        "read_paper",
        "propose_hypothesis",
        "refine_factor_spec",
        "run_experiment",
        "run_robustness_test",
        "request_lean_verification",
        "reject_branch",
        "promote_branch",
        "finish_research",
    ]
    payload: dict[str, JsonValue]
```

### RewardBreakdown

```python
class RewardBreakdown(BaseModel):
    evidence_quality: float
    out_of_sample_quality: float
    robustness: float
    reproducibility: float
    research_progress: float
    llm_cost_penalty: float
    compute_cost_penalty: float
    redundancy_penalty: float
    complexity_penalty: float
    hard_failure: str | None
    total: float
    reward_version: str
```

### Environment

```text
validate action
-> capability check
-> budget preflight
-> execute allowed tool/experiment
-> deterministic verifiers
-> semantic auxiliary graders
-> reward calculation
-> state transition
-> checkpoint
-> lineage write
```

The policy cannot mutate reward or verifier implementations.

## 17. RLVR task formulations

Start with tasks that have strong machine-verifiable outcomes:

1. FactorSpec generation against gold critical fields.
2. Next-action selection where legal/illegal and productive/redundant actions are known.
3. Failure classification and recovery-action selection.
4. Research completion decisions where required validators and terminal-state rules are deterministic.

Multi-step RL follows after one-step formulations are stable.
