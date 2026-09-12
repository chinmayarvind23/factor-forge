# Monthly corporate-action execution

The monthly engine now exposes explicit action accounting as an opt-in policy paired
with pending-liability collateral. Existing action-rejection declarations retain their
semantics and saved results.

The monthly account uses rational arithmetic to apply split ratios, signed entitlements
and payment phases. Each observation is reconciled with full Decimal ledger replay,
including complete claim records. This retains an independent check instead of copying
the ledger's balances into the execution state. Action-bearing accounts deliberately
use full replay; only action-free accounts retain the existing ledger cache.

Availability must precede or equal effect. Events before the initial account and ambiguous
same-security effects are rejected before signal formation. Effective events precede
payment and trade phases at the same clock. Borrow permissions do not grow with splits.
Known terminal payouts become claims; unknown held exits stop execution.

Target sizing continues to use post-fee NAV, including pending claims. A staged batch
must separately satisfy actual cash reserves before any fills are committed. Automatically
shrinking targets would change the declared allocation, so an infeasible batch stops the
run. Positive claims never fund trades until paid; negative claims reserve cash separately.

Terminal liquidation closes shares and charges trade costs. A fixed claim payable later
remains explicitly marked in terminal NAV. The engine does not invent an early payment or
extend the declared sample. The profile still has zero ongoing financing/borrow costs,
bounded sources and exact representable quantities.

Verification uses authored accounts and full-ledger comparisons, with no research benchmark
rerun. See [the accounting contract and checks](../pending-cash-claims.md).
