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

This pure funding component is implemented and covered by six hand-account checks.
It does not establish event authenticity, announcement timing or settlement evidence.
The monthly backtest integration remains to be implemented; the monthly engine's
existing corporate-action rejection remains active until that integration is verified.
The published historical signal study remains on its separate adjusted-price path.
