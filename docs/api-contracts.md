# API Contracts

Implemented local surface: health, readiness, run creation and run lookup. The remaining
operations below are design contracts. Local mode requires `FACTORFORGE_MODE=local`, a
loopback peer and host, and either no Origin (CLI) or `http://127.0.0.1:3001` (browser).
Launch Uvicorn with `--no-proxy-headers` so forwarded headers cannot supply the peer identity.
Local records are ephemeral; this surface is not production authentication.
Requests larger than 16 KiB return a typed 413 `REQUEST_TOO_LARGE` response before JSON parsing.

## Principles

- Public product operations use REST.
- Long-running work returns a run ID quickly.
- Internal LEAN verification uses gRPC.
- GraphQL is read-oriented and appears after the core REST surface is stable.
- Requests are versioned and typed.
- Side-effecting creation endpoints accept an idempotency key.

## REST

### POST `/api/v1/research-runs`

Requires `Idempotency-Key` (1-128 letters, digits, underscores or hyphens). A repeated key
and identical validated request returns the same 202 receipt. Different input with the same
key returns 409 `IDEMPOTENCY_CONFLICT`. The idea is 3-4000 characters after stripping outer
whitespace; cost must be positive and at most $100 with at most two decimal places; wall time
is 1-86400 seconds; experiment count is 1-100. These are request bounds, not cost authorization.

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

The local skeleton currently returns the original idea, a normalized `brief` string, the
three `max_*` budget fields, `created_at`, `mode: "local"`, and an `events` array containing
`status` and `created_at`. It stops at `BRIEF_NORMALIZED`; no research verdict is produced.

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
