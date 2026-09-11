# Monthly raw-price strategy contract

`domain.raw_strategy.RawStrategySpec` declares `factor-spec-v3` with the fixed profile
`monthly-raw-price-post-fee-v1`. It preserves FactorSpec v2 and its total-return source and
pre-trade NAV assumptions. A valid v3 model is a complete declaration for the supported
subset; it is not evidence that source bytes, calendar sessions or a funded backtest passed.

The profile permits original fixtures, monthly formation, one later session's open, one
nonoverlapping cohort, equal weights and exact unit long/short sleeves. It rejects annual
timing, overlapping vintages, value weighting, nonzero carry, corporate-action execution,
HAC and implicit signal transformations. Required policy fields make these choices part of
the canonical record. Public projection and identity helpers revalidate copied models.

## Source roles

Each `TableReference` binds a dataset version, object name, schema interpretation and exact
artifact reference. The dataset versions must exactly match the declared manifests.

| Role | Wire schema | Bound fields |
| --- | --- | --- |
| Monthly signal and historical universe | `monthly-source-v1` | Explicit concept; fixed `value`, `security_id`, `available_at`, `period_end`, `revision`; membership `included`, `effective_at`, `available_at` |
| Raw market | `raw-market-source-v1` | `quotes`, `actions`, `borrow_grants` |
| Benchmark and risk-free comparison | `interval-returns-v1` | `rows`, `source_id`, `series_id`, `start_at`, `end_at`, `available_at`, `cumulative_return` |

The initial adapter consumes one monthly bundle shared by signal and membership roles and
one interval bundle with distinct `benchmark` and `risk_free` selectors. Market quotes have
raw price semantics. Comparison rows contain exact cumulative returns over the observed
close-to-close interval; an annual yield or a generic daily return column cannot substitute.

Monthly inputs require instant contexts and an explicit revision policy. The formula grammar
and dimensional checks reuse the existing C6 implementation. Only scalar arithmetic and
`compound_return` are supported here; annual `delta` is rejected. Compounding requires
return units, sufficient consecutive history and an explicit lookback. Metadata coverage
includes civil-month lag and history per dataset. Actual availability, requested months,
revision conflicts and missing rows remain checks on verified source bytes.

## Scheduling and funding

`sample_start` names the baseline date: the first actual monthly formation close with initial
cash and no holdings. An executor must derive that close from the bound calendar and reject
a date that does not match it. The model contains no caller-authored `FormationPlan`.
The terminal policy liquidates at the last sample session with costs. Drawdown observations
include the baseline and session closes; intraday funding observations are a separate gate.
Supported metrics are net mean, net Sharpe, maximum drawdown and turnover.

`RawPortfolio` composes the existing `AllocationSpec` with `post_fee_nav` sizing,
`current_short_liability_cash_reserve_v1` collateral and
`exact_terminating_decimal_18_v1` quantities. Combined commission and slippage must be below
5000 basis points, satisfying the sufficient slope gate for unit long/short sleeves.
The [funding calculator](funding.md) still needs actual pre-trade marked state and quotes.
The declaration cannot prove terminating quantities, a valid finite short loan, free cash
at every required observation or a feasible broker execution. Initial capital belongs in
the executor's separately bound run request. Simultaneous reference-quote batches and cash
slippage charges are explicit engineering assumptions.

## Identity and admission boundaries

Canonical identity binds the complete declaration. `execution_sha256` omits `source_refs`,
factor ID, version label and display name, normalizes input and metric ordering and formula
whitespace, and retains
exact numeric source lexemes so distinct Decimal constants cannot collide through AST float
rounding. It retains all versioned economic and data choices. Neither hash authenticates
the content of a referenced artifact.

Each source table and calendar is nonempty JSON of at most 8 MiB; manifests are at most
256 KiB. `unique_artifacts()` rejects conflicting metadata for a repeated hash and caps the
complete unique reference inventory at 64 MiB before admission reads. It includes source
evidence, calendar, manifests and all table roles. `table_references()` and
`required_coverage()` expose validated planning metadata.

The runtime must still verify every referenced byte, manifest object binding, rights and
original-fixture provenance; derive calendar sessions; validate source coverage and historical
IDs; check the eight-security limit and allocation feasibility; enforce empty action records,
borrow terms, exact arithmetic and funding; and retain the resulting execution evidence.
Parsing this schema alone must not mark a hypothesis testable or a research run complete.
