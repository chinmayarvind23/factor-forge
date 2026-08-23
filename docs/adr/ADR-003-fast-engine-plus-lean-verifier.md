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

## Switch condition

If translation disagreements dominate development cost, strengthen the shared canonical strategy representation or move more experiments into LEAN.
