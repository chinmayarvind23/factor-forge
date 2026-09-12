"""Hand accounts distinguish unsettled NAV from spendable cash and liability reserves."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from factorforge.backtests.cash_claims import ClaimCollateralObservation, observe_claim_collateral
from factorforge.domain.accounting import CashClaim


def claim(identity: str, amount: str) -> CashClaim:
    """Use explicit original cash entitlements, separate from any market-data claim."""
    return CashClaim(
        event_id=identity,
        security_id="A",
        kind="cash_dividend",
        signed_amount_usd=Decimal(amount),
        pay_at=datetime(2024, 2, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "amounts,nav,free,status",
    [
        ((), 100, 100, "funded"),
        (("20",), 120, 100, "funded"),
        (("-20",), 80, 80, "funded"),
        (("200", "-150"), 150, -50, "unfunded"),
        (("-150",), -50, -50, "insolvent"),
    ],
)
def test_pending_claim_hand_accounts(
    amounts: tuple[str, ...], nav: int, free: int, status: str
) -> None:
    """Offsetting NAV claims cannot hide the cash needed to settle a short dividend."""
    result = observe_claim_collateral(
        cash_usd=Decimal(100),
        notionals=(),
        claims=tuple(claim(str(i), v) for i, v in enumerate(amounts)),
    )
    assert result.nav_usd.as_fraction() == nav
    assert result.free_cash_usd.as_fraction() == free
    assert result.status == status
    assert ClaimCollateralObservation.model_validate_json(result.canonical_bytes()) == result


def test_claim_settlement_and_duplicate_rejection() -> None:
    """Settlement preserves NAV; duplicate entitlements cannot double count."""
    pending = observe_claim_collateral(
        cash_usd=Decimal(100), notionals=(), claims=(claim("a", "20"),)
    )
    paid = observe_claim_collateral(cash_usd=Decimal(120), notionals=(), claims=())
    assert pending.nav_usd == paid.nav_usd
    assert paid.free_cash_usd.as_fraction() - pending.free_cash_usd.as_fraction() == 20
    with pytest.raises(ValidationError):
        observe_claim_collateral(
            cash_usd=Decimal(100), notionals=(), claims=(claim("a", "20"),) * 2
        )
