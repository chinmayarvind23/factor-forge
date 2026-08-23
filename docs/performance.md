# Performance and Scalability

## Workload shape

FactorForge is compute-heavy and request-light. The web/API tier serves low-rate control operations. The worker tier runs long, bursty experiments.

Web requests and research jobs therefore use separate latency budgets.

## Latency budgets

Interactive:

```text
auth + request validation        < 300 ms typical
create run                       < 500 ms typical
read status/report metadata      < 500 ms typical
```

Research:

```text
literature retrieval             seconds
model synthesis                  seconds to minutes
factor experiment                seconds to minutes
LEAN verification                minutes
full autonomous run              tens of minutes
```

Research latency is measured by stage rather than presented as HTTP latency.

## Optimization order

1. remove unnecessary model calls,
2. shrink context,
3. reuse approved literature/data work,
4. batch compatible model calls,
5. parallelize independent experiments,
6. optimize Polars queries,
7. cache demonstrated hot lookups,
8. scale worker slots.

## Runtime study

The 46-minute to 18-minute reduction requires a paired workload with equivalent cases and model/provider constraints.

Measure contributions separately:

- parallel experiment slots,
- literature cache,
- context compaction,
- model routing,
- fewer redundant tool calls,
- early pruning,
- success/failure memory reuse,
- Polars vectorization,
- deferring LEAN until promotion.

## Cost

Track LLM, experiment compute, storage, search/database, and observability cost.

The `$0.84` public figure is scoped to average LLM cost per paper unless the results define a broader number.

## API scaling

FastAPI is stateless.

```text
ALB/API Gateway
      |
  API replicas
      |
RDS / Redis / S3
```

No critical research state lives only in API memory.

## Worker scaling

EKS Jobs scale by queue backlog and resource class.

```text
small-cpu
large-cpu
memory-heavy
spark-job
lean-verifier
gpu-training
```

GPU nodes appear only for a measured PyTorch/TRL training need.

## Backpressure

SQS queue depth and age provide backpressure signals. The system can delay or reject new expensive runs when queue age, worker saturation, or critical dependency health exceeds policy.

## Cache keys

Example literature key:

```text
sha256(
  normalized_query
  + corpus_version
  + retrieval_config_version
  + embedding_model_version
)
```

A cache hit preserves provenance.

## Spark and Kafka

PySpark is used only when distributed joins/backfills have measured value. Kafka belongs in a market-data replay/streaming lab, not as a decorative queue for low-rate research jobs.
