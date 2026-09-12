"""Hand-account corporate-action checks exercise the admitted monthly execution path."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from test_monthly_admission import MemoryStore, original_strategy
from test_monthly_backtest import execute, replace_source, two_formation_strategy

from factorforge.backtests import accounting
from factorforge.backtests.cash_claims import ClaimCollateralObservation
from factorforge.backtests.monthly import MonthlyRun
from factorforge.domain.raw_strategy import RawStrategySpec


def action_spec() -> tuple[RawStrategySpec, MemoryStore]:
    """Opt in explicitly; the frozen rejection policy and its receipts remain unchanged."""
    spec, store = original_strategy()
    wire = spec.model_dump(mode="json")
    wire["policies"]["corporate_actions"] = "explicit_entitlement_payment_v1"
    wire["portfolio"]["collateral"] = "short_and_pending_liability_cash_reserve_v1"
    return RawStrategySpec.model_validate_json(json.dumps(wire)), store


def event(**changes: Any) -> dict[str, Any]:
    """Use a declared one-dollar entitlement after entry with separately dated payment."""
    return {
        "event_id": "dividend-A",
        "security_id": "A",
        "kind": "cash_dividend",
        "available_at": "2024-05-01T12:00:00Z",
        "effective_at": "2024-05-02T13:30:00Z",
        "pay_at": "2024-05-03T13:30:00Z",
        "old_shares": None,
        "new_shares": None,
        "cash_per_share": "1",
    } | changes


def reconcile(result: MonthlyRun, spec: RawStrategySpec, store: MemoryStore) -> None:
    """Compare every independent monthly balance with full Decimal ledger replay."""
    from factorforge.domain.raw_market import RawMarketSource

    market = RawMarketSource.model_validate_json(store.values[spec.market.table.artifact.sha256])
    for observed in result.observations:
        ids = {phase.event_id for phase in observed.snapshot.applied_phases}
        expected = accounting.account_at(
            initial_cash=Decimal("1002"),
            start_at=result.observations[0].at,
            at=observed.at,
            fills=tuple(fill for fill in result.fills if fill.fill_id in ids),
            actions=market.actions,
            marks=observed.marks,
            costs=spec.costs,
        )
        assert observed.snapshot == expected
    assert MonthlyRun.model_validate_json(result.canonical_bytes()) == result


@pytest.mark.parametrize("security,amount", [("A", Decimal("10")), ("B", Decimal("-10"))])
@pytest.mark.parametrize("paid", [True, False])
@pytest.mark.parametrize("whole", [False, True])
def test_signed_entitlement_and_payment(
    security: str, amount: Decimal, paid: bool, whole: bool
) -> None:
    """Claims survive until payment, including liquidation before the declared pay date."""
    spec, store = action_spec()
    if whole:
        wire = spec.model_dump(mode="json")
        wire["portfolio"]["quantity"] = "whole_shares_toward_zero_v1"
        spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    action = event(
        security_id=security, pay_at="2024-05-03T13:30:00Z" if paid else "2024-05-06T13:30:00Z"
    )
    spec = replace_source(spec, store, "market", lambda value: value["actions"].append(action))
    result = execute(spec, store)
    assert result.status == "completed", result.failure_code
    pending = next(row for row in result.observations if row.snapshot.claims)
    assert pending.snapshot.claims[0].signed_amount_usd == amount
    assert pending.snapshot.cash_usd == Decimal("1000")
    assert isinstance(pending.collateral, ClaimCollateralObservation)
    assert pending.collateral.claim_liability_reserve_usd.as_fraction() == max(-amount, 0)
    terminal = result.observations[-1].snapshot
    assert terminal.nav_usd == Decimal("1057.98") + amount
    assert bool(terminal.claims) != paid
    assert terminal.cash_usd == Decimal("1057.98") + (amount if paid else 0)
    reconcile(result, spec, store)


@pytest.mark.parametrize("field", ["actions", "collateral"])
def test_policy_pair_must_be_consistent(field: str) -> None:
    """A caller cannot opt into event economics while declaring the old reserve rule."""
    spec, _ = original_strategy()
    wire = spec.model_dump(mode="json")
    if field == "actions":
        wire["policies"]["corporate_actions"] = "explicit_entitlement_payment_v1"
    else:
        wire["portfolio"]["collateral"] = "short_and_pending_liability_cash_reserve_v1"
    with pytest.raises(ValidationError, match="pending-liability collateral"):
        RawStrategySpec.model_validate_json(json.dumps(wire))


def test_empty_event_inventory_still_records_declared_reserve_policy() -> None:
    """Opting in before any event preserves a consistent policy across saved observations."""
    spec, store = action_spec()
    result = execute(spec, store)
    assert result.status == "completed", result.failure_code
    assert all(
        isinstance(row.collateral, ClaimCollateralObservation) for row in result.observations
    )
    reconcile(result, spec, store)


def test_entitlement_precedes_entry_at_same_instant() -> None:
    """Buying at the effect clock never earns the preceding entitlement."""
    spec, store = action_spec()
    action = event(effective_at="2024-05-01T13:30:00Z", pay_at="2024-05-01T13:30:00Z")
    spec = replace_source(spec, store, "market", lambda value: value["actions"].append(action))
    result = execute(spec, store)
    assert result.status == "completed", result.failure_code
    assert result.observations[-1].snapshot.nav_usd == Decimal("1057.98")
    reconcile(result, spec, store)


@pytest.mark.parametrize("security,loan", [("A", "10"), ("B", "20"), ("B", "10")])
def test_split_preserves_value_and_requires_actual_borrow_capacity(
    security: str, loan: str
) -> None:
    """A two-for-one raw-price split scales shares, never the declared loan permission."""
    spec, store = action_spec()
    action = event(
        security_id=security,
        kind="split",
        old_shares="1",
        new_shares="2",
        pay_at=None,
        cash_per_share=None,
    )

    def change(value: dict[str, Any]) -> None:
        """Author matching raw split quotes and an independently declared loan limit."""
        value["actions"].append(action)
        value["borrow_grants"][0]["maximum_short_shares"] = loan
        for quote in value["quotes"]:
            if quote["security_id"] == security and quote["observed_at"] >= action["effective_at"]:
                quote["price_usd"] = str(Decimal(quote["price_usd"]) / 2)

    spec = replace_source(spec, store, "market", change)
    result = execute(spec, store)
    if security == "B" and loan == "10":
        assert result.failure_code == "MONTHLY_BORROW_EXPIRED_OR_INSUFFICIENT"
        assert len(result.fills) == 2
    else:
        assert result.status == "completed", result.failure_code
        assert result.observations[-1].snapshot.nav_usd == Decimal("1057.98")
        assert result.fills[-2 if security == "A" else -1].signed_quantity == (
            -20 if security == "A" else 20
        )
    reconcile(result, spec, store)


@pytest.mark.parametrize("cash", ["104", None])
def test_terminal_exit_replaces_position_with_claim(cash: str | None) -> None:
    """Known exit has no generated trade fee; a held unknown payout stops execution."""
    spec, store = action_spec()
    action = event(
        kind="terminal_exit", cash_per_share=cash, pay_at="2024-05-06T13:30:00Z" if cash else None
    )
    spec = replace_source(spec, store, "market", lambda value: value["actions"].append(action))
    result = execute(spec, store)
    if cash is None:
        assert result.failure_code == "ACCOUNTING_UNKNOWN_EXIT"
        assert len(result.fills) == 2
    else:
        assert result.status == "completed", result.failure_code
        assert len(result.fills) == 3
        assert result.observations[-1].snapshot.nav_usd == Decimal("1059.02")
        assert result.observations[-1].snapshot.claims[0].signed_amount_usd == 1040
        reconcile(result, spec, store)


@pytest.mark.parametrize("invalid", ["late", "ambiguous", "before_baseline"])
def test_invalid_action_schedule_fails_before_signals(invalid: str) -> None:
    """No outcome can influence admission of the declared event chronology."""
    spec, store = action_spec()
    action = event()
    if invalid == "late":
        action["available_at"] = "2024-05-02T13:30:01Z"
    elif invalid == "before_baseline":
        action["effective_at"] = "2024-04-30T13:30:00Z"
        action["available_at"] = "2024-04-30T12:00:00Z"
    actions = [action]
    if invalid == "ambiguous":
        actions.append(action | {"event_id": "duplicate-effect"})
    spec = replace_source(spec, store, "market", lambda value: value["actions"].extend(actions))
    result = execute(spec, store)
    assert (
        result.failure_code
        == {
            "late": "MONTHLY_ACTION_UNAVAILABLE",
            "ambiguous": "ACCOUNTING_AMBIGUOUS_EVENT_ORDER",
            "before_baseline": "ACCOUNTING_EVENT_BEFORE_START",
        }[invalid]
    )
    assert result.formations == () and result.fills == ()


@pytest.mark.parametrize("paid", [False, True])
def test_later_rebalance_cannot_spend_unpaid_receivable(paid: bool) -> None:
    """The same intended allocation is fundable only after actual payment, not entitlement."""
    spec, store = two_formation_strategy()
    wire = spec.model_dump(mode="json")
    wire["policies"]["corporate_actions"] = "explicit_entitlement_payment_v1"
    wire["portfolio"]["collateral"] = "short_and_pending_liability_cash_reserve_v1"
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))

    def change(value: dict[str, Any]) -> None:
        """Provide enough borrow capacity to isolate cash funding from loan rejection."""
        value["actions"].append(
            event(pay_at="2024-06-03T13:30:00Z" if paid else "2024-06-05T13:30:00Z")
        )
        for grant in value["borrow_grants"]:
            grant["maximum_short_shares"] = "100"

    spec = replace_source(spec, store, "market", change)
    result = execute(spec, store)
    if paid:
        assert result.status == "completed", result.failure_code
        assert len(result.batches) == 3
        assert result.observations[-1].snapshot.nav_usd == Decimal("1012.02")
    else:
        assert result.failure_code == "FUNDING_COLLATERAL_DEFICIT"
        assert len(result.batches) == 1 and len(result.fills) == 2
        assert result.observations[-1].phase == "before_entry"
        assert result.observations[-1].snapshot.cash_usd == 1002
        assert result.observations[-1].snapshot.fees_usd == 0
    reconcile(result, spec, store)


def test_later_allocation_cannot_reenter_exited_security() -> None:
    """An available quote does not authorize trading a security after its terminal exit."""
    spec, store = two_formation_strategy()
    wire = spec.model_dump(mode="json")
    wire["policies"]["corporate_actions"] = "explicit_entitlement_payment_v1"
    wire["portfolio"]["collateral"] = "short_and_pending_liability_cash_reserve_v1"
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    action = event(kind="terminal_exit", cash_per_share="100")

    def change(value: dict[str, Any]) -> None:
        """Allow initial exact shares so the later terminal-security gate is exercised."""
        value["actions"].append(action)
        for grant in value["borrow_grants"]:
            grant["maximum_short_shares"] = "100"

    spec = replace_source(spec, store, "market", change)
    result = execute(spec, store)
    assert result.failure_code == "ACCOUNTING_TRADE_AFTER_EXIT"
    assert len(result.batches) == 1 and len(result.fills) == 2
    reconcile(result, spec, store)
