# Observability

## Objectives

Observability must answer:

- what state was the research run in,
- what did the model see,
- which tool did it choose,
- what did the tool receive and return,
- what experiment actually ran,
- where time and money were spent,
- why the system stopped or continued,
- which artifact supports each report claim.

## Trace model

One research run creates one root trace.

```text
research_run
  normalize_brief
  literature_search
    elastic_bm25
    dense_search
    neo4j_expand
  hypothesis_generation
  plan
  experiment_dispatch
  experiment_job
    data_load
    factor_compute
    backtest
    validation
  critic
  lean_verify
  report
```

## Correlation identifiers

Every event carries `run_id`, `trace_id`, `experiment_id` where relevant, `hypothesis_id` where relevant, `factor_spec_version`, and `dataset_version`.

## LangSmith

Use LangSmith for semantic AI traces:

- prompt/model calls,
- subagent handoffs,
- tool selection,
- state-transition context,
- token/cost data,
- datasets/evals,
- human feedback.

## OpenTelemetry

Use OTel for vendor-neutral distributed tracing and metrics across FastAPI, SQS producer/consumer, worker controller, Kubernetes jobs, LEAN gRPC, search calls, and database calls.

## Metrics

Agent:

```text
factorforge_agent_steps_total
factorforge_tool_calls_total
factorforge_invalid_tool_calls_total
factorforge_subagent_handoffs_total
factorforge_budget_stops_total
factorforge_checkpoint_resumes_total
```

Research:

```text
factorforge_experiments_total
factorforge_experiment_failures_total
factorforge_lean_disagreements_total
factorforge_leakage_blocks_total
factorforge_lineage_failures_total
factorforge_research_completion_seconds
```

Cost:

```text
factorforge_llm_cost_usd
factorforge_cloud_compute_cost_usd
factorforge_tokens_input_total
factorforge_tokens_output_total
```

System:

```text
http_request_duration_seconds
sqs_queue_age_seconds
worker_job_duration_seconds
redis_cache_hit_ratio
db_pool_saturation
search_latency_seconds
```

## Logs

Use structured JSON logs. Do not emit secrets, raw auth tokens, unrestricted user data, or entire licensed datasets.

## Dashboards

Useful dashboards:

1. research funnel,
2. failure categories,
3. tool utility,
4. runtime decomposition,
5. cost decomposition,
6. queue/worker health,
7. benchmark regressions,
8. memory reuse and invalidation.

## LangSmith Engine

Use trace analysis to identify recurring failure clusters and propose eval cases or code/prompt changes. Proposed fixes still pass ordinary code review and benchmark gates. Trace analysis never self-merges production changes.
