# Conditional cross-sectional targets

`build_targets` accepts one `CrossSection` of preselected scalar signals, an eligible security
inventory and an explicit `PortfolioSpec`. It returns every retained row's bucket and exact
rational weight, exclusions, formation times, and input/policy hashes. This is conditional
target planning. Source references identify inputs; this function does not verify their bytes,
select source facts, establish point-in-time eligibility, fund positions or execute orders.

The table path uses Polars for the one-to-one eligible-inventory join, missing-input filtering,
ordering and contiguous bucket assignment. Before table operations, Python assigns ordinals
using exact Decimal comparisons. This preserves differences finer than Float64 and avoids
forcing the formula interpreter's 50-digit results into Decimal128. It is a bounded correctness
baseline, not a fully vectorized formula engine or a measured speed improvement. The upstream
caller remains responsible for deriving each selected signal under its declared formula.

There are at most 10,000 eligible IDs and 10,000 selected rows per formation. Duplicate IDs,
malformed numbers and supplied nonpositive capitalization fail before exclusions. Missing
signals, rows or required value-weight inputs use the explicit `fail` or `exclude_at_formation`
policy. Equal weighting does not invent capitalization when value weighting was requested.

After exclusions, the [versioned partition policy](factor-contract.md) distributes the remainder
to the low-signal buckets. Every bucket must meet its minimum. Direction is applied afterward,
and each extreme sleeve normalizes independently to positive or negative one. Interior rows
retain zero weights. Reduced rational numerator/denominator strings preserve exact weights;
there is no implicit fractional-share or residual-rounding convention.

`estimate_trade_cost` compares target weights with supplied drifted weights on the same
pre-trade NAV basis. Absent targets liquidate existing holdings. Turnover is the sum of absolute
weight changes; commission and slippage multiply that total by the declared basis-point rates.
This trade-only estimate excludes ongoing borrow, financing and interest, which require elapsed
exposures and an explicit funding policy. Rational intermediates have precision bounds so
adversarial denominators cannot grow without limit.

Reloaded plans validate policy identity, inventory, bucket counts, signs, equal-weight ratios
and unit sleeve totals. Cost records validate arithmetic. These checks do not authenticate an
unsigned report or prove that selected rows match the referenced source. Funding and execution
remain separate gates, including the fee-related free-cash constraint described in the factor
contract. Engineering test coverage is not empirical factor-replication evidence.

The original eight-security, two-formation development oracle was frozen before its engine
comparison. All four formation/weighting plans and both supplied-drift cost cases matched
exactly, including exclusions, buckets, rational weights, turnover and fees. The comparison
used preselected signals and a synthetic calendar descriptor; it did not test source selection,
calendar admission, funding or a continuous fee-adjusted account. All 28 comparison assertions
passed and saved code/input/output evidence was verified separately. The initial 33 unit tests
cover this conditional slice and its malformed-input and saved-record checks.

Implementation references: [Polars joins](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.join.html)
and [sorting](https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.sort.html).
