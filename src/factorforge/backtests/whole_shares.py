"""Explicit whole-share targets retain the ideal sizing request and actual rounded economics."""

from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.backtests.funding import (
    FundingPosition,
    FundingRequest,
    exact_accounting,
    exact_quantity,
    solve_post_fee,
)
from factorforge.domain.accounting import LedgerInput, Positive
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, Identifier
from factorforge.domain.targets import Rational


class SharePrice(LedgerInput):
    """Execution supplies admitted contemporaneous quotes; this pure type grants no provenance."""

    security_id: Identifier
    price_usd: Positive


def _calculate(
    request: FundingRequest, prices: tuple[SharePrice, ...]
) -> tuple[tuple[FundingPosition, ...], tuple[Fraction, ...]]:
    """Truncate ideal signed holdings toward zero, then recompute costs and funding from trades.

    Rounding is not an optimizer: an infeasible rounded rebalance is rejected, never repaired
    by searching quantities. Both sleeves must survive and remain below actual post-fee NAV.
    """
    ideal = solve_post_fee(request)
    quotes = {row.security_id: Fraction(row.price_usd) for row in prices}
    keys = tuple(row.security_id for row in ideal.positions)
    if tuple(quotes) != keys or len(quotes) != len(prices):
        raise ValueError("Prices must exactly match the sorted funding inventory")
    positions = []
    for row in ideal.positions:
        price = quotes[row.security_id]
        old = row.old_notional_usd.as_fraction()
        if (old / price).denominator != 1:
            raise ValueError("Whole-share policy requires whole existing holdings")
        quantity = Fraction(int(row.target_notional_usd.as_fraction() / price))
        exact_quantity(quantity)
        target, trade = quantity * price, quantity * price - old
        exact_accounting(target)
        exact_accounting(trade)
        exact_quantity(trade / price)
        positions.append(
            FundingPosition(
                security_id=row.security_id,
                old_notional_usd=row.old_notional_usd,
                target_weight=row.target_weight,
                target_notional_usd=Rational.from_fraction(target),
                trade_notional_usd=Rational.from_fraction(trade),
            )
        )
    turnover = sum((abs(row.trade_notional_usd.as_fraction()) for row in positions), Fraction(0))
    commission = turnover * Fraction(request.costs.commission_bps, 10000)
    slippage = turnover * Fraction(request.costs.slippage_bps, 10000)
    nav = request.pre_trade_nav_usd.as_fraction() - commission - slippage
    targets = [row.target_notional_usd.as_fraction() for row in positions]
    long = sum((value for value in targets if value > 0), Fraction(0))
    short = -sum((value for value in targets if value < 0), Fraction(0))
    # Free cash is NAV minus the long sleeve under the declared short-liability reserve.
    if nav <= 0 or max(long, short) > nav:
        raise ValueError("Rounded holdings exceed funded exposure")
    if request.purpose == "rebalance" and (long == 0 or short == 0):
        raise ValueError("Rounding removed a required sleeve")
    values = nav, turnover, commission, slippage
    for value in (*values, nav - sum(targets), nav - long):
        exact_accounting(value)
    return tuple(positions), values


class WholeSharePlan(Contract):
    """A separate schema preserves actual post-fee NAV, not the ideal continuous sizing NAV."""

    schema_version: Literal["whole-share-funding-plan-v1"] = "whole-share-funding-plan-v1"
    request: FundingRequest
    request_sha256: Digest
    prices: Annotated[tuple[SharePrice, ...], Field(min_length=1, max_length=8)]
    positions: Annotated[tuple[FundingPosition, ...], Field(max_length=8)]
    sizing_nav_usd: Rational
    absolute_trade_notional_usd: Rational
    commission_usd: Rational
    slippage_usd: Rational

    @model_validator(mode="after")
    def exact_rounded_result(self) -> Self:
        """Saved outputs must recompute from the unchanged continuous request and exact quotes."""
        positions, values = _calculate(self.request, self.prices)
        observed = tuple(
            value.as_fraction()
            for value in (
                self.sizing_nav_usd,
                self.absolute_trade_notional_usd,
                self.commission_usd,
                self.slippage_usd,
            )
        )
        if (
            self.request_sha256 != self.request.sha256
            or self.positions != positions
            or observed != values
        ):
            raise ValueError("Whole-share receipt differs from its input economics")
        return self


def size_whole_shares(request: FundingRequest, prices: tuple[SharePrice, ...]) -> WholeSharePlan:
    """Admit bounded inputs before arithmetic and preserve failure without a sizing fallback."""
    try:
        request = FundingRequest.model_validate(request)
        if type(prices) is not tuple or not 1 <= len(prices) <= 8:
            raise ValueError("Bounded prices required")
        prices = tuple(
            sorted(
                (SharePrice.model_validate(row) for row in prices), key=lambda row: row.security_id
            )
        )
        positions, (nav, turnover, commission, slippage) = _calculate(request, prices)
        return WholeSharePlan(
            request=request,
            request_sha256=request.sha256,
            prices=prices,
            positions=positions,
            sizing_nav_usd=Rational.from_fraction(nav),
            absolute_trade_notional_usd=Rational.from_fraction(turnover),
            commission_usd=Rational.from_fraction(commission),
            slippage_usd=Rational.from_fraction(slippage),
        )
    except (ValueError, TypeError):
        raise ResearchError(
            "WHOLE_SHARE_SIZING_INVALID", "Whole-share sizing is infeasible.", 422
        ) from None
