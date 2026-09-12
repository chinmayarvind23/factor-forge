# Explicit whole-share sizing

Status: implemented for the monthly raw-price simulator.

The continuous post-fee solver can produce share quantities that are not terminating
decimals at ordinary prices. Its exact-share policy intentionally rejects those orders.
Historical execution therefore needs a declared quantity rule, rather than incidental
rounding inside decimal conversion.

`whole_shares_toward_zero_v1` solves the existing continuous target first, divides each
target notional by its admitted price, and truncates signed holdings toward zero. It
then computes actual traded notionals, commissions, slippage and post-fee NAV. The
quantity policy is part of the strategy identity and cannot change on receipt reload.
The resulting long and short sleeves may differ in size; residual cash remains explicit.

The batch must retain both sleeves at rebalance, each no greater than actual NAV, and
meet the existing short-liability cash reserve. Existing holdings must be integral.
An infeasible rounded result stops before fills. A separate optimizer could search
smaller allocations, but would add a selection rule and another research choice. This
version performs no such search and makes no optimality claim.

The new funding receipt records prices and recomputes all values on reload. Execution
also binds those prices to emitted quotes and retains the complete source/code closure.
Decimal precision is checked before Fraction conversion. The existing eight-security,
source-admission, action and history limits remain explicit capability constraints.

Verification includes hand arithmetic, missing/duplicate prices, fractional existing
holdings, erased sleeves, hostile decimal precision, altered receipts, complete entry
and liquidation, and deterministic replay. LEAN source contract v4 independently
implements single-entry whole-share sizing with rational division before truncation.
The authored flat-price case matches four closing NAV/cash/fee observations and four
actual fills. The same image verifies the existing exact-share case. Multi-rebalance
whole-share comparison remains outside that LEAN profile.
