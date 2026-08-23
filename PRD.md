# FactorForge Product Requirements Document

## 1. Problem statement

Quantitative research is a chain of work, not a single model call. A researcher starts with a vague idea, finds prior work, converts prose into a testable specification, obtains point-in-time data, writes an implementation, selects a baseline, runs experiments, checks statistical validity, investigates failures, and decides whether the idea deserves another iteration.

The process is slow because it crosses literature search, data engineering, code generation, backtesting, statistics, experiment tracking, and research writing. It is also easy to create false confidence through lookahead leakage, survivorship bias, transaction-cost omissions, weak baselines, repeated testing, or undocumented manual changes.

FactorForge automates the mechanical parts while keeping the research contract explicit, bounded, observable, and reproducible.

## 2. Product definition

FactorForge is an autonomous quantitative-research platform that converts a natural-language investment idea into a reproducible research packet:

- relevant literature and source provenance,
- one or more typed hypotheses,
- a versioned `FactorSpec`,
- dataset and point-in-time assumptions,
- generated or selected strategy code,
- sandboxed experiment runs,
- walk-forward and purged-validation results,
- transaction-cost and robustness analysis,
- independent LEAN verification when required,
- a structured research verdict,
- a complete lineage bundle,
- reusable memory from successful and failed experiments.

The system does not place live trades, connect to brokerage execution APIs, or present historical backtests as investment advice.

## 3. Primary user

The primary user is a quantitative researcher, ML engineer, or technically sophisticated investor investigating equity-factor ideas with stronger reproducibility and less manual glue work.

## 4. Core user workflow

1. Authenticate.
2. Submit an investment idea and research constraints.
3. Review the normalized research brief.
4. Retrieve relevant papers and prior experiments.
5. Produce a ranked queue of typed hypotheses.
6. Build a research plan with explicit data, baseline, metrics, budget, and stop conditions.
7. Execute experiments in an isolated environment.
8. Validate results with point-in-time, time-series-aware methodology.
9. Compare candidate and baseline across windows, costs, and seeds where relevant.
10. Send promoted strategies through independent LEAN verification.
11. Record the verdict and complete lineage.
12. Reuse prior successes and failures in later runs.
13. Produce a research report with citations, tables, limitations, and reproduction commands.

## 5. Functional requirements

### Research specification

- Accept a loose natural-language idea.
- Normalize it into a typed `ResearchBrief`.
- Produce one or more typed `FactorSpec` objects.
- Require explicit universe, signal inputs, timing assumptions, formula, rebalance rule, weighting, neutralization, transaction-cost model, benchmark, and expected direction before backtesting.

### Literature and knowledge

- Search approved literature sources.
- Combine lexical, dense, and citation-graph signals.
- Record stable paper identifiers and retrieval evidence.
- Extract factor definitions into typed structures.
- Detect near-duplicate hypotheses.
- Retrieve related prior FactorForge experiments without treating them as authoritative evidence.

### Experiments

- Generate a bounded experiment plan.
- Run untrusted generated code outside the control-plane process.
- Enforce time, CPU, memory, process, filesystem, and network limits.
- Pin seeds and environment versions.
- Capture stdout, stderr, metrics, artifacts, and terminal state.
- Support one-variable-at-a-time ablations before larger sweeps.
- Support parallel experiment slots with a total run budget.

### Quant validation

- Enforce point-in-time joins and configurable reporting lags.
- Support walk-forward evaluation.
- Support purged cross-validation with embargo.
- Include transaction costs and slippage assumptions.
- Calculate Sharpe, Sortino, maximum drawdown, turnover, information coefficient, CAGR where appropriate, and HAC/Newey-West t-statistics.
- Surface sample size and uncertainty.
- Track repeated-hypothesis testing and factor-selection multiplicity.
- Cross-check selected statistics in R.
- Independently rerun promoted strategies in LEAN.

### Agent harness

- Keep orchestration state outside the model.
- Use explicit state transitions.
- Checkpoint after durable research boundaries.
- Enforce iteration, wall-clock, token, and dollar budgets in code.
- Keep tool schemas typed and versioned.
- Treat peer-agent output as untrusted data.
- Use deterministic verification before semantic model judging.
- Require human approval for high-cost or irreversible operations.
- Support graceful stop and resume.

### Memory and lineage

- Preserve successful and failed experiments.
- Link papers, hypotheses, factors, datasets, code, experiments, strategies, and results.
- Separate durable source-of-truth state from rebuildable indexes.
- Preserve model, prompt, tool, environment, data, code, and metric versions.
- Make every published benchmark traceable to a single manifest.

### Interface

- Web UI for starting runs, inspecting state, reviewing evidence, and comparing experiments.
- REST API for product operations.
- gRPC for the isolated LEAN verification service.
- Read-oriented GraphQL surface for research/eval exploration after the core API is stable.
- MCP tool endpoints for standardized tool access.
- A2A interoperability demonstration with one remote specialized agent.

### Autonomous research lifecycle

The research product preserves the following explicit stages:

1. evaluation harness,
2. hypothesis generation,
3. literature retrieval,
4. experiment execution,
5. result evaluation,
6. critic loop,
7. iteration scheduling,
8. independent verification,
9. evidence-constrained report generation and end-to-end reproduction.

Each stage has typed inputs/outputs and failure states. No stage can hide missing evidence by returning plausible prose.

### Agentic RL and RLVR extension

After the deterministic agent baseline and eval harness are stable:

- expose a versioned research environment with `reset` and `step`,
- define typed research states, observations, and actions,
- preserve successful and failed trajectories as rollout data,
- create reward functions from deterministic/reference-based verifiers,
- train supervised and preference baselines before RL,
- run RLVR on tasks with strong verifiable reward,
- run multi-step agentic-RL experiments inside the same sandbox and budget boundaries,
- keep the 45-case public release benchmark outside training,
- compare the learned policy with the prompted LangGraph baseline,
- refuse promotion when the learned policy increases hard execution-path violations.

The model policy never gains live-trading authority.

## 6. Non-functional requirements

### Correctness

A run fails closed when a required data version, timestamp assumption, sandbox control, metric contract, or lineage field is missing.

### Reproducibility

Every benchmark run includes enough information to rerun the same code against the same data snapshot with the same FactorSpec, seeds, engine versions, and model/prompt identifiers.

### Safety

Generated experiment code cannot reach live trading credentials, production databases, arbitrary host files, or unrestricted external network endpoints.

### Reliability

Long-running runs checkpoint after meaningful boundaries and can resume after worker loss without repeating already-accepted expensive steps.

### Observability

Every research run has a trace ID. Tool calls, state transitions, model calls, retrieval, backtests, validators, retries, approvals, latency, and cost are observable.

### Cost

The orchestrator maintains a per-run budget. Each expensive step has a preflight estimate and post-run actual. New research work stops when the remaining budget cannot safely cover the next step.

### Performance

Interactive API operations are measured separately from asynchronous research latency. Backtests and validation are compute jobs, not long HTTP requests.

### Security

Identity, authorization, secrets, workload identity, data access, and tool permissions are enforced outside model prompts.

## 7. Data requirements

### Durable source material

- paper metadata and allowed text/abstract content,
- point-in-time market and fundamentals snapshots used by benchmarks,
- dataset manifests,
- factor specifications,
- research briefs,
- experiment configs,
- generated code,
- backtest results,
- validation outputs,
- reports,
- trace and lineage manifests.

### Rebuildable material

- embeddings,
- Elasticsearch indexes,
- Weaviate indexes,
- Neo4j projections derived from canonical records,
- Redis cache entries,
- dashboard aggregates.

### Data providers

Provider adapters keep provenance explicit. Suitable sources include Semantic Scholar and OpenAlex for literature metadata, SEC EDGAR/XBRL for public company fundamentals, public factor libraries for reference series, and a documented market-data provider or pinned public snapshot for prices and corporate actions.

A benchmark case is not accepted if its data license or point-in-time semantics are unknown.

## 8. `FactorSpec` contract

A factor cannot enter the backtest engine until it has a validated specification.

```text
FactorSpec
  factor_id
  version
  name
  source_papers[]
  universe
  eligibility_rules[]
  signal_inputs[]
  formula
  lookback_window
  formation_lag
  holding_period
  rebalance_schedule
  weighting
  winsorization
  standardization
  neutralization
  missing_data_policy
  corporate_action_policy
  point_in_time_policy
  transaction_cost_model
  benchmark
  expected_direction
  evaluation_metrics[]
  reproducibility_seed_set[]
```

The language model can propose the structure. Pydantic validation and deterministic domain rules decide whether the structure is executable.

## 9. Release evidence gates

The final release is accepted only when saved evidence supports all of the following:

- 43 of 45 benchmark research cases reach a valid terminal state without human correction during the run.
- 11 of 15 published equity-factor cases reproduce within the predeclared Sharpe/t-stat tolerance.
- 13 of 15 published-factor cases have a correctly extracted `FactorSpec`.
- Every benchmark case has complete prompt, data, code, config, backtest, trace, and experiment lineage.
- The trace corpus contains at least 1,200 agent/tool spans.
- The controlled performance study reproduces the runtime reduction from 46 minutes to 18 minutes under a documented workload.
- The controlled cost study supports an average LLM cost of $0.84 per paper under the documented model and pricing snapshot.
- No run that violates a leakage, sandbox, authorization, lineage, or forbidden-tool invariant can pass the execution-path scorecard.11. Product validation

The product is useful if it makes research faster while increasing, rather than reducing, the evidence available for review.

The strongest proof is a run where a reviewer can inspect the source papers, FactorSpec, data version, generated code, point-in-time checks, experiment logs, validation statistics, independent LEAN result, agent trajectory, failure decisions, and final verdict from one run identifier.

## 12. Competitive and reference landscape

FactorForge sits between:

- autonomous scientific-research agents,
- quant research notebooks and backtest engines,
- experiment-tracking systems,
- agent harnesses,
- factor libraries and quantitative platforms.

Its differentiator is the integration contract. A plausible hypothesis, successful code execution, or high Sharpe ratio is never enough by itself. Each stage has a typed contract and an independent verification path.

## 13. Explicit non-goals

- live trade execution,
- brokerage account integration,
- autonomous capital allocation,
- portfolio management for real users,
- claiming causal economic truth from a backtest,
- replacing a human investment committee,
- unbounded web access from generated code,
- an unrestricted general-purpose coding agent,
- one giant multi-agent conversation with implicit state,
- putting every listed technology in the first working version.

## 14. Failure cases that define the product

The system must visibly handle:

- malformed or vague research idea,
- paper retrieval with contradictory definitions,
- factor extraction missing timing assumptions,
- stale or unversioned dataset,
- lookahead leakage,
- survivorship bias,
- invalid as-of join,
- transaction costs flipping a strategy from positive to negative,
- unstable Sharpe across windows,
- statistically insignificant improvement,
- multiple-testing concern,
- backtest-engine disagreement,
- sandbox timeout,
- sandbox memory exhaustion,
- blocked network exfiltration,
- generated-code crash,
- LLM provider failure,
- duplicate agent loop,
- budget exhaustion,
- worker loss and resume,
- poisoned paper text or tool output,
- missing lineage field,
- corrupted cache,
- stale search index,
- unauthorized tool request.

## 15. Definition of done

FactorForge is complete when a clean checkout can reproduce the public benchmark and evidence bundle, the demo shows both a successful research run and meaningful failure handling.

## 16. Agentic learning acceptance

The learning extension is complete when:

- the environment can replay a pinned case deterministically where deterministic behavior is expected,
- actions are schema-validated and capability-gated,
- reward components are versioned and independently recomputable,
- failed experiments appear in training/evaluation data with explicit failure labels,
- training and public benchmark cases are separated by immutable case IDs,
- at least one prompted baseline, one supervised/preference baseline, and one RLVR or multi-step RL policy are compared,
- reward-hacking adversarial cases exist,
- a learned policy cannot bypass hard research, security, budget, or lineage checks,
- policy promotion is evidence-driven and reversible.
