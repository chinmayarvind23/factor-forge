"""Exact collateral treatment for unsettled corporate-action receivables and liabilities."""

from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.backtests.funding import (
    CollateralObservation,
    SignedNotional,
    _add,
    _cash_fraction,
    _collateral_status,
    _sum,
    _wire,
    observe_collateral,
)
from factorforge.domain.accounting import CashClaim
from factorforge.domain.factors import Contract
from factorforge.domain.targets import Rational


class ClaimCollateralObservation(Contract):
    """Receivables add NAV; unsettled liabilities reserve cash without netting receivables."""

    schema_version: Literal["claim-collateral-observation-v1"] = "claim-collateral-observation-v1"
    policy: Literal["short_and_pending_liability_cash_reserve_v1"] = (
        "short_and_pending_liability_cash_reserve_v1"
    )
    base: CollateralObservation
    claims: Annotated[tuple[CashClaim, ...], Field(max_length=2048)]
    claim_nav_usd: Rational
    claim_liability_reserve_usd: Rational
    free_cash_usd: Rational
    nav_usd: Rational
    status: Literal["funded", "unfunded", "insolvent"]
    failure_code: Literal["FUNDING_COLLATERAL_DEFICIT", "FUNDING_INSOLVENT"] | None

    @model_validator(mode="after")
    def exact_claims(self) -> Self:
        """Recompute retained totals and reject duplicate claims or forged funding labels."""
        ids = tuple(claim.event_id for claim in self.claims)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Claims must have unique, sorted event identities")
        amounts = tuple(_cash_fraction(claim.signed_amount_usd) for claim in self.claims)
        total = _sum(amounts)
        reserve = _sum(-amount for amount in amounts if amount < 0)
        nav = _add(self.base.nav_usd.as_fraction(), total)
        free = _add(self.base.free_cash_usd.as_fraction(), -reserve)
        status, code = _collateral_status(nav, free)
        if (
            self.claim_nav_usd.as_fraction(),
            self.claim_liability_reserve_usd.as_fraction(),
            self.nav_usd.as_fraction(),
            self.free_cash_usd.as_fraction(),
            self.status,
            self.failure_code,
        ) != (total, reserve, nav, free, status, code):
            raise ValueError("Claim collateral differs from its retained exact account")
        return self


def observe_claim_collateral(
    *, cash_usd: Decimal, notionals: tuple[SignedNotional, ...], claims: tuple[CashClaim, ...]
) -> ClaimCollateralObservation:
    """Observe already derived ledger claims; this does not grant event or quote admission.

    Positive claims never increase spendable cash. Each negative claim reserves its full
    amount, even when another claim offsets its NAV impact. Settlement timing and source
    provenance remain the ledger caller's responsibility.
    """
    if type(claims) is not tuple or len(claims) > 2048:
        raise ValueError("Claim inventory must be a bounded tuple")
    verified = tuple(
        sorted((CashClaim.model_validate(c) for c in claims), key=lambda c: c.event_id)
    )
    base = observe_collateral(cash_usd=cash_usd, notionals=notionals)
    amounts = tuple(_cash_fraction(claim.signed_amount_usd) for claim in verified)
    total = _sum(amounts)
    reserve = _sum(-amount for amount in amounts if amount < Fraction(0))
    nav = _add(base.nav_usd.as_fraction(), total)
    free = _add(base.free_cash_usd.as_fraction(), -reserve)
    status, code = _collateral_status(nav, free)
    return ClaimCollateralObservation(
        base=base,
        claims=verified,
        claim_nav_usd=_wire(total),
        claim_liability_reserve_usd=_wire(reserve),
        nav_usd=_wire(nav),
        free_cash_usd=_wire(free),
        status=status,
        failure_code=code,
    )
