# Monthly raw-price simulator

`backtests.monthly.run_monthly(spec, store, initial_cash_usd=..., evaluated_at=...)`
executes the v3 strategy profile with fixture or declared observed inputs. It connects verified source admission,
calendar scheduling, point-in-time monthly selection, Polars allocation, exact post-fee
funding, generated signed-share fills, ledger replay and complete-path metrics.

This is a trusted local library function. It does not execute generated Python, grant an
API capability, place live orders or establish independent LEAN agreement. The full
autonomous research graph remains separate unfinished work.

## Execution and evidence

The request binds the full strategy, initial cash and aware evaluation clock. Before any
signal or account calculation, the runner saves its request, source-admission receipt,
the actual installed source files, environment versions and prepared record. Stored source
is evidence; it is never imported from an artifact as execution authority.

The bound calendar determines monthly formation closes and the next opening session.
The sample must start at the actual first formation close and end at an actual session.
Limits are eight security IDs, 512 calendar sessions, 12 formations and 100,000 requested
signal-history cells. The default policy rejects corporate actions; an explicit
[action and pending-claim policy](pending-cash-claims.md) enables splits, dividends and
terminal exits. Nonzero carry remains unsupported. Monthly
signals use formation-known revisions; prices and finite short-loan grants must be known
when consumed. An expired held loan stops execution at the next required observation.

Each opening rebalance uses the previously formed allocation. The engine solves exact
post-fee notionals and checks every quantity, fee and balance before adding the atomic
fill batch. The exact quantity policy rejects unrepresentable shares. Operators can instead
declare `portfolio.quantity = "whole_shares_toward_zero_v1"` before execution; this
policy truncates ideal signed holdings toward zero and recomputes fees from actual trades.
It retains residual cash, requires both sleeves to survive, and rejects any rounded
exposure above actual post-fee NAV. Neither policy injects cash or silently falls back.
Every required open and close checks raw marks, ledger balances and current-short-liability
cash reserves. Terminal close liquidates all positions with costs. Missing data or a
funding failure retains the observed prefix and disables completed sample metrics.

Net and benchmark reports use the complete calendar-derived close inventory and exact
aligned benchmark/risk-free intervals. Entry fees belong to the first genuine interval;
drawdown includes the baseline and closes. Intraday funding checks remain distinct.
Benchmark data do not affect formation. Undefined statistics remain explicitly unavailable.
Archived real market/risk-free reference imports are described in
[French daily normalization](french-daily-normalization.md).

Between trades, execution reuses its privately derived ledger and values it at the
current marks. A changed fill inventory triggers full replay. This optimization requires
the existing action-free, zero-carry profile; collateral and loan checks still run at
every observation. Tests compare every snapshot against full replay for fees, rank
reversal and a zero-turnover rebalance. The authored two-formation reversal case needs
4 full replays for 54 observations. This is an engineering workload, not a measured
end-to-end research speedup. The calendar and output-size limits remain unchanged.

The returned `MonthlyRun` is also saved canonically. It contains request and preparation
references, plans, selections, allocations, funding batches, fills, observations, metric
paths and terminal status. Reload validation checks source/trade identities and requires
completed metric paths to match retained account closes and final funded liquidation.
Those checks establish internal consistency; replay from verified inputs establishes
whether a saved run describes the actual computation.

## Original evidence

The committed fixture in `data/backtests/monthly-raw-v1` froze independent expected outputs
before implementation. With initial cash of $1,002 and total trade costs of 10 basis points,
execution generates ten long shares and ten short shares, then liquidates for $1,057.98. All nine account
observations and both fee batches match the reference. A second run starting at $1,000 fails
with `FUNDING_QUANTITY_PRECISION` before any fill, rather than rounding its rational target.

The working-tree real-storage check verified 33 referenced objects and 22 actual source files.
The focused suite has 41 passing cases, including later reconstitution, disappearing IDs,
late observations, loan failures, collateral deficits, source corruption and altered saved
results. These are engineering fixtures, not historical returns or published-factor
replications. Cloud execution, strategy-wide budget integration and independent LEAN
verification are not established by this simulator.

## Whole-share execution

The whole-share policy uses a separate `whole-share-funding-plan-v1` receipt containing
the continuous funding request, admitted sizing prices, rounded notionals and actual
costs. Existing holdings must be whole shares. Missing prices, fractional carry, erased
sleeves and infeasible rounded rebalances fail before emitting the batch. Decimal inputs
retain the ledger's precision bounds before rational conversion. Liquidation uses the
same policy and closes the actual holdings.

An authored flat-price case at $101 and $97 enters nine long shares and ten short shares,
then closes both positions. At 10 basis points total costs and $1,002 initial cash, the
four fills incur $3.758 and leave $998.242. Disk verification covers all 36 reachable
objects, and identical execution reproduces the result. This is engineering evidence;
provider-specific historical normalization and larger portfolios remain development work.

Independent LEAN source contract v4 now verifies this single-entry whole-share case,
including all four closing NAVs, cash balances and fee totals, plus the four actual
fills. The same executable also passes the existing exact-share case. See
[the comparison](../data/verification/lean-whole-shares-v4/comparison.json) and
[the sizing decision](adr/whole-share-sizing.md) for the constraints and tradeoff.
