# Pending corporate-action cash claims

The exact ledger already distinguishes economic entitlement from settlement. A long
dividend creates a positive cash claim; a short dividend creates a liability. Cash
changes at payment, while the signed claim contributes to NAV before payment.

[Claim collateral accounting](../src/factorforge/backtests/cash_claims.py) adds an
explicit funding observation for that interval:

- NAV equals marked cash/positions plus signed pending claims.
- Positive receivables do not increase available cash before settlement.
- Each pending liability reserves its full cash amount, separately from the existing
  short-position reserve. Positive claims do not offset this cash requirement.
- Insolvency takes precedence over a cash-reserve deficit in the retained status.

For example, $100 cash with a $200 receivable and a $150 payable has $150 NAV but
negative $50 free cash. It is unfunded under this declared conservative reserve
policy. This is an internal financing policy, not a simulation of broker margin.

The new `claim-collateral-observation-v1` retains the existing marked collateral
observation, all individual claims and exact rational totals. Validation recomputes
totals and rejects repeated claim identities. A $20 receivable becoming $20 cash
preserves NAV while increasing spendable cash by $20.

The monthly engine accepts this accounting through an explicit pair of strategy settings:
`policies.corporate_actions = "explicit_entitlement_payment_v1"` and
`portfolio.collateral = "short_and_pending_liability_cash_reserve_v1"`.
Existing strategies declaring `reject_any_events` retain that behavior.

At each open and close, an independent rational account applies effective events before
payments and trades. The engine compares cash, fees, positions and the complete claim
inventory against Decimal ledger replay. Splits change share quantities; declared borrow
capacity must still cover the resulting short. Terminal exits remove the position and
prohibit subsequent entry. Unknown exit terms fail while shares are held.

Rebalance sizing includes signed claims in NAV. Before committing fills, a separate cash
check rejects any allocation that would spend a receivable or leave liabilities unreserved.
The engine stops rather than silently changing the strategy's target weights. At the final
close all shares are liquidated; fixed unpaid claims may remain in NAV and are retained in
the terminal snapshot. Settlement after that close is outside the performance sample.

Six pure funding checks and 23 monthly action checks cover these rules, including payment
at an entry instant, payment after liquidation, split borrow capacity, invalid event timing
and rejection of an unfunded later rebalance. This establishes accounting behavior on
authored inputs; event authenticity still depends on admitted source evidence. The published
historical signal study remains on its separate adjusted-price path.
