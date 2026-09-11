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

`orchestration/budgets.py` adds [pure research budget transitions](research-budgets.md).
Integer USD millionths are reserved before dispatch; immutable operation IDs prevent repeat
dispatch permission, and unknown charges retain capacity. Actual estimate overruns stay
recorded and block new work. The original deadline and saved clock watermark survive restart.
`orchestration/postgres_budgets.py` binds reservations to the canonical owner/request and
commits them under the run's PostgreSQL row lock. Settlement verifies retained result bytes
and records immutable cost observations in the same transaction boundary. Graph integration
remains a worker responsibility; this does not expand the browser's normalization flow.

`orchestration/monthly_worker.py` connects one immutable monthly request to durable experiment
reservation and result settlement. Replays recover the verified stored `MonthlyRun`; an
unsettled reservation requires reconciliation. The server derives operation identity from
the canonical run and request hash. The broader research graph composes this worker with
literature retrieval, hypothesis creation and validation stages.

The independent literature path uses `domain/literature.py` and `retrieval/lexical.py` for
immutable documents and bounded BM25 ranking. `evaluation/retrieval.py` requires complete binary
judgments and separates answerable and no-relevant query denominators; its CLI archives the
input bytes and actual result. `providers/ollama.py` supplies fixed, versioned loopback profiles
with no tools, retries, endpoint redirection or inferred dollar cost. `retrieval/extraction.py`
retains raw source pages, a versioned whitespace transform, prepared prompt and provider record.
`domain/extraction.py` validates observations without treating parsing as accuracy, while
`domain/formula.py` interprets a closed arithmetic grammar without executing Python. See the
[extraction contract](extraction-contract.md) and [formula language](formula-language.md).

`domain/factors.py` binds required strategy policies and data roles in immutable, revalidated
contracts. It checks closed formula names, units, temporal operators and declared history.
`factors/hypotheses.py` verifies bounded artifacts and manifest compatibility before ranking
up to 64 hypotheses. It retains blockers and exact-execution duplicates. Queue admission is
declared-contract and artifact readiness only; actual rows, accounting and sandbox admission
remain later gates. See the [factor contract](factor-contract.md).

`domain/accounting.py` and `backtests/accounting.py` now replay conditional signed-share fills,
split/dividend/exit phases, explicit trade fees and exact-time raw-price valuation. Unknown held
terminal outcomes block accounting. This [conditional ledger](conditional-accounting.md) has
hand-worked engineering references; it is not yet a strategy executor or funding admission gate.

`domain/targets.py` and `factors/targets.py` produce conditional target weights from selected
scalar signals. The shared [allocation template](allocations.md) has its own identity and
declares unit sleeves independently of execution sizing. The existing v2 target wrapper
retains its original canonical bytes and pre-trade NAV convention.
Polars joins and partitions the eligible table, with exact Decimal ordinals
and rational sleeve weights. Removed target identities remain in drift-based turnover and
trade-fee estimates. The [target contract](conditional-targets.md) preserves the distinction
between these calculations and source selection, funding or order execution.

`data/monthly_signals.py` verifies an input-only fact/membership artifact and selects the
consecutive monthly instant observations declared by `domain/monthly_signals.py`. Publication
is bounded by formation, economic lag preserves civil dates, and missing months have no stale
fallback. The [monthly adapter](monthly-signals.md) retains every selected or missing cell and
passes derived scalars to target construction. Calendar admission, full FactorSpec checks and
execution remain separate boundaries.

`domain/raw_market.py` and `data/raw_market.py` define and verify the new
[raw market and interval sources](raw-market.md). Raw opening/closing prices, complete
action coverage, bounded original short-loan grants and exact comparison intervals remain
separate roles. Parsing preserves unavailable observations and unknown exits; execution must
check their admissibility against every required calendar clock.

`backtests/funding.py` solves the bounded exact [post-fee funding equation](funding.md)
with rational arithmetic. It charges commission and slippage on every absolute trade
notional, rejects quantities that cannot be represented exactly, and retains observed
cash, current short-liability reserves and funding failures. This pure notional model
does not grant execution permission or verify quotes and loan availability.

`domain/raw_strategy.py` declares the distinct [monthly raw-price v3 contract](raw-strategy.md).
It binds actual source roles, original-fixture scope, monthly timing and exact post-fee
policies. Its canonical declaration and normalized execution identity remain separate;
neither is an execution result. The complete original inputs and independently calculated
outputs in `data/backtests/monthly-raw-v1` are frozen before the executor is implemented.

`backtests/admission.py` supplies [monthly source admission](monthly-admission.md): canonical
manifests and rights pass before economic data reads, every object role and byte identity is
verified, and execution receives a pinned source snapshot. The receipt binds the declared
strategy and source closure. Actual calendar, funding and execution gates remain separate.

`backtests/monthly.py` connects those gates in the [original monthly simulator](monthly-backtest.md).
It saves request, admission and source/environment preparation before calculations, derives
formation and trade clocks, generates exact funded batches and replays the ledger at every
required observation. Failed paths retain their prefix; completed metrics require retained
account closes and terminal liquidation. The autonomous research graph remains unfinished.

`backtests/performance.py` computes [conditional NAV metrics](conditional-metrics.md) from
a complete declared close inventory. Entry fees remain in the first full interval and
drawdown baseline. Invalid rate or execution inventories disable only their dependent
metrics; known terminal insolvency remains a reported loss. These calculations use a fixed
Decimal context and have independent hand references, without inferring a complete calendar.

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
    experiments.py
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
    staging.py
    docker.py
    process.py
    runner.py
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
class ExperimentSpec(Contract):
    schema_version: Literal["experiment-spec-v1"]
    experiment_id: UUID
    run_id: UUID
    owner_issuer: str
    owner_subject: str
    factor_spec_sha256: Digest
    code: ArtifactRef
    config: ArtifactRef
    input_refs: tuple[ArtifactRef, ...]
    seed: int
    engine: Literal["python"]
    profile: Literal["python-bounded-v1", "python-bounded-v2"]
```

This abbreviated schema reflects the implemented internal experiment request; production
validators bound every field and inventory. Fixed server policy supplies resource limits
and image identity separately. Requests cannot select a daemon, image, path, command,
environment or network override. Run ownership lookup and FactorSpec hash resolution are
still trusted-caller admission work. See the [sandbox contract](sandbox.md).

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

## 9a. Implemented local Python sandbox

`domain/experiments.py` separates a strict experiment request, fixed declared policy,
verified-input admission and controller-reported terminal result. `sandbox/policy.py`
reconstructs the principal, requires `execute_experiment` and exact owner issuer/subject
before artifact reads, and checks canonical allowlisted image identity and actual bytes.
Existing browser/Cognito permissions do not gain execution capability.

`sandbox/staging.py` revalidates admission and rereads at most 16 MiB of unique source
bytes before creating a private random bundle. Fixed code/config/input paths and an
inventory bind roles to references. POSIX permissions and protected Windows owner/SYSTEM
ACLs protect the private outer directory; the container receives its readonly mount root.
Pinned ancestors, exclusive file creation and identity-checked leaf cleanup avoid following
symlinks/reparse replacements or recursively deleting an untrusted path.

`sandbox/docker.py` targets an explicitly configured local daemon and one Linux/amd64
stdlib Python image by immutable identity. It checks cgroup/resource prerequisites,
builds fixed arguments and verifies the effective container before code starts. Required
controls include UID/GID65532, readonly root/input, private namespaces, one CPU, 512 MiB
memory with no additional swap, 64 PIDs, bounded tmpfs and the pinned no-network seccomp
asset. The [sandbox profile](sandbox.md) records exact settings and compatibility limits.

`sandbox/process.py` bounds controller process output and elapsed calls. Its termination
does not prove that Docker stopped a container. `sandbox/runner.py` retains start/code/
environment references before creation, checks mounted bytes again in the container,
captures bounded stdout/stderr and separately verifies nonce-owned cleanup. A successful
process is an execution observation; economic correctness needs an independent validator.

When container removal remains uncertain, a once-evaluated staging cleanup callback keeps
the entire private bundle and closes handles. A failed callback also retains inputs.
An indeterminate create cannot become confirmed cleanup merely because a later listing is
empty. Automatic reconciliation after controller crashes and canonical run/FactorSpec
admission are unfinished. The arithmetic smoke and separate eight-case Docker acceptance
suite preserve observed filesystem/syscall/resource denials and cleanup; image dependency
findings remain open in the [results](results.md).

## 10. LEAN verifier contract

`interop/lean` implements a [conditional price-only contract](lean-verifier.md), generated
protobuf bindings and a cooperative handler. It opens no listener and supplies no runtime
backend. Health distinguishes adapter liveness from engine readiness. Authorization precedes
artifact reads; source and expected NAV remain separate. A prepared start artifact precedes
backend invocation, while terminal records distinguish attempted work and uncertain cleanup.
Independent engine execution and authenticated service hosting remain unfinished.

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
