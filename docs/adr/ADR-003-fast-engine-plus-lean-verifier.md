# ADR-003: Use a fast research engine plus independent LEAN verification

## Context

Quant research needs quick iteration and independent confirmation.

## Decision

Use Polars/Python for the primary transparent factor research engine. Reimplement promoted strategies through LEAN for independent verification.

## Alternatives

- LEAN only,
- custom engine only.

## Tradeoff

Maintaining a canonical strategy specification and translation layer adds work.

## Evidence

Track iteration latency and cross-engine disagreement rate.

The first implemented slice is conditional accounting and target planning. Polars handles
the eligible table join, filtering and bucket partition; exact Decimal ordering and rational
weights remain bounded Python steps to preserve precision. Frozen hand examples test arithmetic.
This is a correctness baseline with no measured speedup and no LEAN comparison yet. Source
selection, execution, funding, full return metrics and independent LEAN verification must be
connected before the system can report an end-to-end research backtest.

## Switch condition

If translation disagreements dominate development cost, strengthen the shared canonical strategy representation or move more experiments into LEAN.
