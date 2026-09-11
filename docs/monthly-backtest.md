# Monthly raw-price simulator

`backtests.monthly.run_monthly(spec, store, initial_cash_usd=..., evaluated_at=...)`
executes the original-fixture v3 strategy profile. It connects verified source admission,
calendar scheduling, point-in-time monthly selection, Polars allocation, exact post-fee
funding, generated signed-share fills, ledger replay and complete-path metrics.

This is a trusted local library function. It does not execute generated Python, grant an
API capability, place live orders or establish independent LEAN agreement. The full
autonomous research graph remains separate unfinished work.

## Execution and evidence

The request binds the full strategy, initial cash and aware evaluation clock. Before any
signal or account calculation, the runner saves its request, source-admission receipt,
22 actual installed source files, environment versions and prepared record. Stored source
is evidence; it is never imported from an artifact as execution authority.

The bound calendar determines monthly formation closes and the next opening session.
The sample must start at the actual first formation close and end at an actual session.
Limits are eight security IDs, 512 calendar sessions, 12 formations and 100,000 requested
signal-history cells. The profile rejects corporate actions and nonzero carry. Monthly
signals use formation-known revisions; prices and finite short-loan grants must be known
when consumed. An expired held loan stops execution at the next required observation.

Each opening rebalance uses the previously formed allocation. The engine solves exact
post-fee notionals and checks every quantity, fee and balance before adding the atomic
fill batch. It never rounds a rejected share quantity or injects cash to repair funding.
Every required open and close checks raw marks, ledger balances and current-short-liability
cash reserves. Terminal close liquidates all positions with costs. Missing data or a
funding failure retains the observed prefix and disables completed sample metrics.

Net and benchmark reports use the complete calendar-derived close inventory and exact
aligned benchmark/risk-free intervals. Entry fees belong to the first genuine interval;
drawdown includes the baseline and closes. Intraday funding checks remain distinct.
Benchmark data do not affect formation. Undefined statistics remain explicitly unavailable.

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
