# API Contracts

## Principles

- Public product operations use REST.
- Long-running work returns a run ID quickly.
- Internal LEAN verification uses gRPC.
- GraphQL is read-oriented and appears after the core REST surface is stable.
- Requests are versioned and typed.
- Side-effecting creation endpoints accept an idempotency key.

## REST

### POST `/api/v1/research-runs`

```json
{
  "idea": "Test whether medium-term residual momentum persists after sector neutralization",
  "max_llm_cost_usd": "5.00",
  "max_wall_time_s": 3600,
  "max_experiments": 12
}
```

Response:

```json
{
  "run_id": "uuid",
  "status": "RECEIVED"
}
```

### GET `/api/v1/research-runs/{run_id}`

Returns state, progress, current budget, terminal reason, and authorized artifact links.

### POST `/api/v1/research-runs/{run_id}/cancel`

Requests cancellation. The orchestrator stops scheduling new work and terminates cancellable jobs.

### GET `/api/v1/research-runs/{run_id}/report`

Returns the structured research report.

### GET `/api/v1/research-runs/{run_id}/lineage`

Returns the immutable evidence manifest and stable identifiers.

### GET `/api/v1/research-runs/{run_id}/experiments`

Returns experiments and validation status.

### POST `/api/v1/research-runs/{run_id}/approvals/{approval_id}`

Records a human decision for a gated action.

### POST `/api/v1/evals/runs`

Starts a reproducible benchmark/eval run.

### GET `/api/v1/evals/runs/{eval_run_id}`

Returns scorecards and artifact references.

### Ops

```text
GET /health
GET /ready
GET /metrics
```

## Error envelope

```json
{
  "error": {
    "code": "BUDGET_EXHAUSTED",
    "message": "The run cannot safely start another experiment within its remaining budget.",
    "retryable": false,
    "trace_id": "..."
  }
}
```

## gRPC LEAN verification

```proto
service LeanVerifier {
  rpc VerifyStrategy(LeanVerificationRequest) returns (LeanVerificationResult);
  rpc Capabilities(CapabilitiesRequest) returns (CapabilitiesResponse);
  rpc Health(HealthRequest) returns (HealthResponse);
}
```

The request carries a canonical strategy specification and immutable data references, not arbitrary shell commands.

## GraphQL

Read-oriented exploration can expose connected research entities without multiplying bespoke read endpoints. State changes remain explicit REST commands.
