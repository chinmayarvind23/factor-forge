# Exact post-fee sizing

`backtests.funding` solves a bounded notional equation and records collateral observations.
It does not authorize a strategy, authenticate a quote, prove stock-borrow availability or
emit a fill. Existing FactorSpec v2 and its pre-trade NAV sizing remain unchanged.

`solve_post_fee(FundingRequest)` accepts positive pre-trade NAV, signed old notionals,
target weights and explicit `LedgerCosts`. Rebalance targets must have exact unit long
and short sleeves. Liquidation targets must all be zero. At most eight security IDs may
appear across old and new inventories; old holdings absent from the targets are liquidated.
Commission and slippage charge every absolute trade notional. All carry rates must be
explicitly zero in this profile.

For equity `E`, old notionals `v`, target weights `w` and combined proportional fee `c`,
the calculator solves:

```text
x + c * sum(abs(x*w_i - v_i)) = E
```

It requires `c * sum(abs(w_i)) < 1` and `E > c * sum(abs(v_i))`. These sufficient gates
make the equation strictly increasing and guarantee a positive root. The implementation
sorts exact rational breakpoints, solves each affine interval and verifies the original
equation exactly. It does not use floating point iteration or a numerical tolerance.
The [self-financing portfolio model](https://web.stanford.edu/~boyd/papers/pdf/cvx_portfolio.pdf)
explains why trading costs reduce portfolio value; this particular bounded root derivation
is the declared FactorForge sizing convention.

The returned `FundingPlan` retains the canonical request and its hash, every old/target/trade
notional, the sizing NAV, total absolute traded notional and separate fees. Its scope is
`pure-post-fee-notional-solution`. Reloaded plans recompute their equation and inventory.
Changing an input order alone does not change the normalized request identity. These checks
do not authenticate the upstream market data or establish execution admission.

| Original arithmetic case | Exact result |
|---|---|
| Equity 1002, fresh unit sleeves, 10 basis points | Each sleeve 1000; absolute notional 2000; fee 2. |
| Equity 1000 under the same policy | Each sleeve `500000/501`; at price 100, shares `5000/501`. |
| Old long 1200, short liability 800, equity 1400, 10 basis points | Sizing NAV `701000/501`; fee `400/501`. |
| Liquidate long 1040 and short liability 980 against equity 1060 | Notional 2020; fee 2.02; remaining NAV 1057.98. |

`exact_quantity(Fraction)` accepts only exact terminating signed values that fit the existing
ledger's input limits: magnitude at most `1e24`, at most 43 coefficient digits and 18 decimal
places. Thus the second example's notional solution exists, but its shares are rejected.
The function receives a quantity, not a notional; the caller must first derive it from a
verified positive quote. No rounding, lot convention or residual allocation is inferred.

`exact_accounting(Fraction)` separately requires a terminating value exactly representable
with 50 coefficient digits and magnitude at most `1e24`. The executor must call this on exact
products, fees and accumulated balances before giving them to the Decimal ledger. Valid
quantities alone do not prove their products fit the accounting precision. Neither helper
performs a context-rounded division. Public conversions reject wrong types, mutated Fraction
internals and unbounded integers before arithmetic.

`observe_collateral(cash_usd=Decimal(...), notionals=(...))` implements the named
`current_short_liability_cash_reserve_v1` policy. Restricted cash equals total current short
liability; free cash is aggregate cash minus that restriction; NAV is aggregate cash plus
signed notionals. The result retains `funded`, `unfunded` or `insolvent` status, a failure code
when needed, and every observed value. Nonpositive NAV takes diagnostic precedence over a
cash deficit. Failed states remain inspectable; the caller must stop rather than treat them
as permission to continue. The observer does not move cash or perform a margin cure.

For cash 1000, long value 1000 and short liability 1010, NAV is positive 990 but free cash
is negative 10. Post-fee sizing therefore does not replace funding checks at every required
open, close and execution boundary. Historical short proceeds are a different restriction
policy and cannot silently substitute for the current-liability reserve. This model supplies
no additional broker margin haircut, loan permission or intraday fill sequence; it is not an
implementation of [broker margin rules](https://www.finra.org/rules-guidance/rulebooks/finra-rules/4210).

Rational operands are checked before each operation. Numerators and denominators are limited
to 2048 bits; the corresponding unreduced cross-products are bounded to 4096 bits, or 4097
for an addition. Reduced results must remain within the operand bound, and serialized values
must also fit the existing 512-digit rational fields. Decimal shape and exponent checks run
before Decimal-to-Fraction allocation. Numeric limits may reject otherwise meaningful
equations; they never justify rounding a rejected result into an admitted one.

The original unit cases are engineering arithmetic, not market measurements or published
factor replication. The planned admitted executor must separately bind calendar, point-in-time
selection, prices, borrow inventory, quantity conversion, generated fills and complete metrics.
