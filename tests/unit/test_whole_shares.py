"""Whole-share sizing keeps actual costs and residual cash independently checkable."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from test_funding import notional, request
from test_monthly_admission import original_strategy
from test_monthly_backtest import execute, replace_source

from factorforge.backtests.whole_shares import SharePrice, WholeSharePlan, size_whole_shares
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec


def prices(a: str = "101", b: str = "97") -> tuple[SharePrice, ...]:
    """Uneven prices make ideal ten-dollar fractions unsuitable for exact-share execution."""
    return (
        SharePrice(security_id="A", price_usd=Decimal(a)),
        SharePrice(security_id="B", price_usd=Decimal(b)),
    )


def test_rounded_shares_costs_and_reload() -> None:
    """Hand amounts: nine long shares, ten short shares, 1879 turnover and 1.879 fees."""
    result = size_whole_shares(request(), prices())
    assert [row.target_notional_usd.as_fraction() for row in result.positions] == [909, -970]
    assert result.absolute_trade_notional_usd.as_fraction() == 1879
    assert result.commission_usd.as_fraction() == Decimal("1.879")
    assert result.sizing_nav_usd.as_fraction() == Decimal("1000.121")
    assert WholeSharePlan.model_validate_json(result.model_dump_json()) == result
    wire = result.model_dump(mode="json")
    wire["commission_usd"]["numerator"] = "0"
    with pytest.raises(ValidationError):
        WholeSharePlan.model_validate_json(json.dumps(wire))


def test_price_precision_is_rejected_before_fraction_allocation() -> None:
    """Hostile decimal exponents fail both direct admission and saved receipt reload."""
    with pytest.raises(ValidationError):
        SharePrice(security_id="A", price_usd=Decimal("1e-1000000000"))
    wire = size_whole_shares(request(), prices()).model_dump(mode="json")
    wire["prices"][0]["price_usd"] = "1e-1000000000"
    with pytest.raises(ValidationError):
        WholeSharePlan.model_validate_json(json.dumps(wire))


def test_rounding_recomputes_costs_before_admitting_exposure() -> None:
    """Rounding a short reduction raises costs: 1000 long would exceed 999.6 actual NAV."""
    value = request(old=(notional("A", 1000), notional("B", -3000)))
    with pytest.raises(ResearchError, match="Whole-share sizing is infeasible"):
        size_whole_shares(value, prices("1", "600"))


@pytest.mark.parametrize("case", ["missing", "duplicate", "fractional_old", "empty_sleeve"])
def test_invalid_price_or_inventory_never_produces_plan(case: str) -> None:
    """No stale price, fractional carry or fully rounded-away sleeve is silently accepted."""
    quotes = prices()
    value = request()
    if case == "missing":
        quotes = quotes[:1]
    elif case == "duplicate":
        quotes = (quotes[0], quotes[0])
    elif case == "fractional_old":
        value = request(old=(notional("A", 100),))
    else:
        quotes = prices("1001", "97")
    with pytest.raises(ResearchError):
        size_whole_shares(value, quotes)


def test_full_monthly_entry_liquidation_and_policy_binding() -> None:
    """Uneven authored prices complete only under the explicitly selected rounding policy."""
    spec, store = original_strategy()

    def uneven_prices(market: dict[str, Any]) -> None:
        """Flat prices isolate independently known entry and exit costs from market returns."""
        for quote in market["quotes"]:
            quote["price_usd"] = "101" if quote["security_id"] == "A" else "97"

    spec = replace_source(spec, store, "market", uneven_prices)
    exact = execute(spec, store)
    assert exact.status == "failed" and exact.failure_code == "FUNDING_QUANTITY_PRECISION"
    wire = spec.model_dump(mode="json")
    wire["portfolio"]["quantity"] = "whole_shares_toward_zero_v1"
    rounded = RawStrategySpec.model_validate_json(json.dumps(wire))
    result = execute(rounded, store)
    assert result.status == "completed", result.failure_code
    assert [row.signed_quantity for row in result.fills] == [9, -10, -9, 10]
    assert result.batches[-1].funding.sizing_nav_usd.as_fraction() == Decimal("998.242")
    assert sum(
        batch.funding.commission_usd.as_fraction() + batch.funding.slippage_usd.as_fraction()
        for batch in result.batches
    ) == Decimal("3.758")
    assert execute(rounded, store) == result
    assert type(result).model_validate_json(result.model_dump_json()) == result
    altered = result.model_dump(mode="json")
    altered["batches"][0]["funding"]["prices"][0]["price_usd"] = "102"
    with pytest.raises(ValidationError):
        type(result).model_validate_json(json.dumps(altered))
