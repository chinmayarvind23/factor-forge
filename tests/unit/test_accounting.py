"""Original hand accounts constrain conditional accounting before any empirical backtest."""

import json
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, DefaultContext, localcontext
from typing import Any, TypedDict

import pytest
from pydantic import ValidationError

from factorforge.backtests.accounting import account_at, ledger_at
from factorforge.domain.accounting import (
    ConditionalFill,
    CorporateAction,
    LedgerCosts,
    LedgerSnapshot,
    PriceMark,
)
from factorforge.domain.errors import ResearchError


class ReplayArguments(TypedDict):
    """Common typed inputs allow repeated hand observations without weakening call checking."""

    initial_cash: Decimal
    start_at: datetime
    fills: tuple[ConditionalFill, ...]
    actions: tuple[CorporateAction, ...]
    costs: LedgerCosts


class ValuationArguments(TypedDict):
    """Shared valuation inputs leave fill/action ordering under test."""

    initial_cash: Decimal
    start_at: datetime
    at: datetime
    marks: tuple[PriceMark, ...]
    costs: LedgerCosts


class FoldZone(tzinfo):
    """A portable authored DST fold isolates absolute-time ordering from timezone databases."""

    def utcoffset(self, value: datetime | None) -> timedelta:
        """The second occurrence of a wall-clock hour has an additional hour of UTC offset."""
        return timedelta(hours=-5 if value is not None and value.fold else -4)

    def dst(self, value: datetime | None) -> timedelta:
        """No additional offset is needed for this narrow authored clock."""
        return timedelta(0)

    def tzname(self, value: datetime | None) -> str:
        """A stable authored label completes the portable timezone interface."""
        return "authored-fold"


def instant(value: str) -> datetime:
    """Parse the authored UTC timestamps used by all hand accounts."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


START = instant("2024-04-29T20:00:00Z")
DATES = ("2024-04-29", "2024-04-30", "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-06")
RAW = {
    "SEC-A": ("100", "102", "104", "52", "51", "53"),
    "SEC-B": ("20", "21", "22"),
    "SEC-C": ("10", "9", "8", "7"),
}


def mark(security: str, day: int) -> PriceMark:
    """Use exact fictional raw closes, without inventing post-exit observations."""
    observed = instant(DATES[day] + "T20:00:00Z")
    return PriceMark(
        source_id=f"price-{security}-{day}",
        security_id=security,
        observed_at=observed,
        available_at=observed,
        price_usd=Decimal(RAW[security][day]),
        adjustment="unadjusted",
        currency="USD",
    )


def fill(security: str, quantity: str, day: int = 0) -> ConditionalFill:
    """An authored conditional fill references its exact observed unadjusted quote."""
    quote = mark(security, day)
    return ConditionalFill(
        fill_id=f"fill-{security}-{day}",
        security_id=security,
        signed_quantity=Decimal(quantity),
        executed_at=quote.observed_at,
        quote=quote,
    )


def costs(commission: int = 0) -> LedgerCosts:
    """Every fee or carry convention is explicitly supplied, including zeroes."""
    return LedgerCosts(
        commission_bps=commission,
        slippage_bps=0,
        annual_borrow_bps=0,
        annual_financing_bps=0,
        annual_interest_bps=0,
    )


def actions() -> tuple[CorporateAction, ...]:
    """Normalize the four original fixture actions into the public accounting contract."""
    return (
        CorporateAction(
            event_id="action-A-split",
            security_id="SEC-A",
            kind="split",
            available_at=instant("2024-04-30T12:00:00Z"),
            effective_at=instant("2024-05-02T13:30:00Z"),
            pay_at=None,
            old_shares=Decimal(1),
            new_shares=Decimal(2),
            cash_per_share=None,
        ),
        CorporateAction(
            event_id="action-A-dividend",
            security_id="SEC-A",
            kind="cash_dividend",
            available_at=instant("2024-05-01T12:00:00Z"),
            effective_at=instant("2024-05-03T13:30:00Z"),
            pay_at=instant("2024-05-06T12:00:00Z"),
            old_shares=None,
            new_shares=None,
            cash_per_share=Decimal(1),
        ),
        CorporateAction(
            event_id="exit-B-known",
            security_id="SEC-B",
            kind="terminal_exit",
            available_at=instant("2024-04-30T15:00:00Z"),
            effective_at=instant("2024-05-02T13:30:00Z"),
            pay_at=instant("2024-05-02T16:00:00Z"),
            old_shares=None,
            new_shares=None,
            cash_per_share=Decimal(24),
        ),
        CorporateAction(
            event_id="exit-C-unknown",
            security_id="SEC-C",
            kind="terminal_exit",
            available_at=instant("2024-05-02T12:00:00Z"),
            effective_at=instant("2024-05-03T13:30:00Z"),
            pay_at=None,
            old_shares=None,
            new_shares=None,
            cash_per_share=None,
        ),
    )


@pytest.mark.parametrize(
    ("holdings", "commission", "expected"),
    [
        ((("SEC-A", "10"),), 0, ("1000", "1020", "1040", "1040", "1040", "1080")),
        ((("SEC-A", "-10"),), 0, ("1000", "980", "960", "960", "960", "920")),
        ((("SEC-A", "5"), ("SEC-B", "-25")), 0, ("1000", "985", "970", "920", "920", "940")),
        ((("SEC-A", "5"), ("SEC-B", "-25")), 10, ("999", "984", "969", "919", "919", "939")),
        ((("SEC-B", "50"),), 0, ("1000", "1050", "1100", "1200", "1200", "1200")),
        ((("SEC-B", "-50"),), 0, ("1000", "950", "900", "800", "800", "800")),
    ],
)
def test_frozen_complete_close_accounts(
    holdings: tuple[tuple[str, str], ...], commission: int, expected: tuple[str, ...]
) -> None:
    """Each frozen close path retains signed corporate actions and its pre-fee baseline."""
    for day, nav in enumerate(expected):
        result = account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=instant(DATES[day] + "T20:00:00Z"),
            fills=tuple(fill(*holding) for holding in holdings),
            actions=actions(),
            marks=tuple(
                mark(security, day) for security, _ in holdings if day < len(RAW[security])
            ),
            costs=costs(commission),
        )
        assert result.nav_usd == Decimal(nav)
        assert result.total_return == Decimal(nav) / Decimal(1000) - 1


@pytest.mark.parametrize("quantity", ["100", "-100"])
def test_unknown_terminal_signed_exposure_blocks_at_effective_time(quantity: str) -> None:
    """A held unknown exit cannot borrow another security's payout or its own stale mark."""
    with pytest.raises(ResearchError) as caught:
        account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=instant("2024-05-03T13:30:00Z"),
            fills=(fill("SEC-C", quantity),),
            actions=actions(),
            marks=(),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_UNKNOWN_EXIT"


def test_explicit_disposal_before_exit_retains_realized_loss() -> None:
    """The authored SEC-C disposal permits a complete account without erasing its loss."""
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-06T20:00:00Z"),
        fills=(fill("SEC-C", "100"), fill("SEC-C", "-100", 3)),
        actions=actions(),
        marks=(),
        costs=costs(),
    )
    assert result.cash_usd == result.nav_usd == Decimal(700)
    assert result.total_return == Decimal("-0.3")


@pytest.mark.parametrize("quantity", ["10", "-10"])
def test_split_and_dividend_phases_preserve_signed_claims(quantity: str) -> None:
    """No price is invented at intraday phases, and dividend payment preserves wealth."""
    initial = Decimal(quantity)
    arguments: ReplayArguments = dict(
        initial_cash=Decimal(1000),
        start_at=START,
        fills=(fill("SEC-A", quantity),),
        actions=actions(),
        costs=costs(),
    )
    split = ledger_at(at=instant("2024-05-02T13:30:00Z"), **arguments)
    assert split.positions[0].signed_shares == initial * 2
    entitlement = ledger_at(at=instant("2024-05-03T13:30:00Z"), **arguments)
    assert sum(c.signed_amount_usd for c in entitlement.claims) == initial * 2
    paid = ledger_at(at=instant("2024-05-06T12:00:00Z"), **arguments)
    assert paid.cash_usd - entitlement.cash_usd == initial * 2
    assert paid.claims == ()
    assert paid.cash_usd == entitlement.cash_usd + sum(
        c.signed_amount_usd for c in entitlement.claims
    )


@pytest.mark.parametrize("quantity", ["50", "-50", "-25"])
def test_known_acquisition_books_claim_then_cash(quantity: str) -> None:
    """Availability does not settle shares, and the signed payable persists until payment."""
    arguments: ReplayArguments = dict(
        initial_cash=Decimal(1000),
        start_at=START,
        fills=(fill("SEC-B", quantity),),
        actions=actions(),
        costs=costs(),
    )
    known = ledger_at(at=instant("2024-04-30T15:00:00Z"), **arguments)
    assert known.positions[0].signed_shares == Decimal(quantity)
    effective = account_at(at=instant("2024-05-02T13:30:00Z"), marks=(), **arguments)
    assert effective.cash_usd == known.cash_usd
    assert effective.positions[0].signed_shares == 0
    assert sum(c.signed_amount_usd for c in effective.claims) == Decimal(quantity) * 24
    paid = account_at(at=instant("2024-05-02T16:00:00Z"), marks=(), **arguments)
    assert paid.nav_usd == effective.nav_usd
    assert paid.cash_usd == known.cash_usd + Decimal(quantity) * 24


def test_entitlement_precedes_same_time_fill_and_survives_later_disposal() -> None:
    """Boundary-only authored prices test ordering without claiming fixture intraday fills."""
    cutoff = actions()[1].effective_at
    quote = mark("SEC-A", 4).model_copy(update={"observed_at": cutoff, "available_at": cutoff})
    bought = fill("SEC-A", "20", 4).model_copy(update={"executed_at": cutoff, "quote": quote})
    result = ledger_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=cutoff,
        fills=(bought,),
        actions=actions(),
        costs=costs(),
    )
    assert sum(c.signed_amount_usd for c in result.claims) == 0
    sold = fill("SEC-A", "-20", 4)
    held = ledger_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-06T12:00:00Z"),
        fills=(fill("SEC-A", "10"), sold),
        actions=actions(),
        costs=costs(),
    )
    assert held.positions[0].signed_shares == 0
    assert held.cash_usd == Decimal(1040)


def test_identical_event_and_fill_replay_is_idempotent_and_order_independent() -> None:
    """Repeated snapshots collapse identical identities and book each event phase only once."""
    kwargs: ValuationArguments = dict(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-06T20:00:00Z"),
        marks=(mark("SEC-A", 5),),
        costs=costs(),
    )
    expected = account_at(fills=(fill("SEC-A", "10"),), actions=actions(), **kwargs)
    actual = account_at(
        fills=(fill("SEC-A", "10"),) * 2, actions=tuple(reversed(actions())) * 2, **kwargs
    )
    assert actual == expected
    assert len({(phase.event_id, phase.phase) for phase in actual.applied_phases}) == len(
        actual.applied_phases
    )


@pytest.mark.parametrize("case", ["action", "fill", "mark", "quote", "cross_kind"])
def test_conflicting_identity_cannot_change_saved_event_economics(case: str) -> None:
    """Reused IDs must retain all recorded fields across marks, fills and economic actions."""
    initial = fill("SEC-A", "10")
    events = actions()
    fills: tuple[ConditionalFill, ...] = (initial,)
    marks: tuple[PriceMark, ...] = (mark("SEC-A", 0),)
    if case == "action":
        events += (events[0].model_copy(update={"new_shares": Decimal(3)}),)
    elif case == "fill":
        fills += (initial.model_copy(update={"signed_quantity": Decimal(11)}),)
    elif case == "mark":
        marks += (marks[0].model_copy(update={"price_usd": Decimal(101)}),)
    elif case == "quote":
        marks = (marks[0].model_copy(update={"price_usd": Decimal(101)}),)
    else:
        events = (events[0].model_copy(update={"event_id": initial.fill_id}),)
    with pytest.raises(ResearchError) as caught:
        account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=fills,
            actions=events,
            marks=marks,
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    "case", ["absent", "stale", "future", "unavailable", "adjusted", "conflict"]
)
def test_valuation_requires_exact_available_unadjusted_prices(case: str) -> None:
    """Incomplete marks are explicit failure; no stale, future or adjusted value fills the gap."""
    quote = mark("SEC-A", 1)
    marks: tuple[PriceMark, ...] = (quote,)
    if case == "absent":
        marks = ()
    elif case == "stale":
        marks = (mark("SEC-A", 0),)
    elif case == "future":
        marks = (mark("SEC-A", 2),)
    elif case == "unavailable":
        marks = (quote.model_copy(update={"available_at": mark("SEC-A", 2).observed_at}),)
    elif case == "adjusted":
        marks = (quote.model_copy(update={"adjustment": "total_return"}),)
    else:
        marks += (quote.model_copy(update={"source_id": "other", "price_usd": Decimal(103)}),)
    with pytest.raises(ResearchError) as caught:
        account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=quote.observed_at,
            fills=(fill("SEC-A", "10"),),
            actions=actions(),
            marks=marks,
            costs=costs(),
        )
    assert caught.value.code == (
        "ACCOUNTING_INPUT_INVALID"
        if case == "adjusted"
        else "ACCOUNTING_MARK_CONFLICT"
        if case == "conflict"
        else "ACCOUNTING_MARK_MISSING"
    )


@pytest.mark.parametrize(
    "case", ["split", "dividend", "known_exit", "payment", "split_cash", "cash_ratio"]
)
def test_contradictory_action_terms_are_rejected(case: str) -> None:
    """Irrelevant ratio fields, unknown dividends and incomplete payment clocks cannot execute."""
    event = actions()[0 if case in {"split", "split_cash"} else 1]
    variants: dict[str, dict[str, Any]] = {
        "split": {"new_shares": None},
        "dividend": {"cash_per_share": None, "pay_at": None},
        "known_exit": {"pay_at": None},
        "payment": {"pay_at": START},
        "split_cash": {"cash_per_share": Decimal(1)},
        "cash_ratio": {"old_shares": Decimal(1)},
    }
    changes = variants[case]
    with pytest.raises(ValidationError):
        CorporateAction.model_validate(event.model_copy(update=changes))


@pytest.mark.parametrize(
    "case",
    ["zero", "security", "stale", "unavailable", "float", "nan", "precision", "negative_price"],
)
def test_forged_fill_models_are_revalidated(case: str) -> None:
    """Nested mutation shortcuts cannot bypass exact quote or bounded decimal admission."""
    item = fill("SEC-A", "10")
    changes: dict[str, Any] = {}
    if case == "zero":
        changes = {"signed_quantity": Decimal(0)}
    elif case == "security":
        changes = {"security_id": "SEC-B"}
    elif case == "stale":
        changes = {"executed_at": mark("SEC-A", 1).observed_at}
    elif case == "unavailable":
        changes = {
            "quote": item.quote.model_copy(update={"available_at": mark("SEC-A", 1).observed_at})
        }
    elif case == "negative_price":
        changes = {"quote": item.quote.model_copy(update={"price_usd": Decimal(-1)})}
    else:
        changes = {
            "signed_quantity": {
                "float": 10.0,
                "nan": Decimal("NaN"),
                "precision": Decimal("1e-1000000"),
            }[case]
        }
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(item.model_copy(update=changes),),
            actions=(),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_INPUT_INVALID"


@pytest.mark.parametrize("case", ["before", "ambiguous", "trade_after_exit", "action_after_exit"])
def test_impossible_event_schedules_fail_closed(case: str) -> None:
    """The ledger never invents an ordering for conflicting events or resurrects exited IDs."""
    events = actions()
    fills: tuple[ConditionalFill, ...] = (fill("SEC-B", "50"),)
    expected = "ACCOUNTING_EVENT_BEFORE_START"
    if case == "before":
        events = (events[0].model_copy(update={"effective_at": instant("2024-04-28T12:00:00Z")}),)
    elif case == "ambiguous":
        events += (events[0].model_copy(update={"event_id": "another-split"}),)
        expected = "ACCOUNTING_AMBIGUOUS_EVENT_ORDER"
    elif case == "trade_after_exit":
        quote = mark("SEC-B", 2).model_copy(
            update={"observed_at": events[2].effective_at, "available_at": events[2].effective_at}
        )
        fills += (
            fills[0].model_copy(
                update={"fill_id": "after", "quote": quote, "executed_at": quote.observed_at}
            ),
        )
        expected = "ACCOUNTING_TRADE_AFTER_EXIT"
    else:
        events += (
            events[0].model_copy(
                update={
                    "security_id": "SEC-B",
                    "event_id": "post-exit",
                    "effective_at": instant("2024-05-03T12:00:00Z"),
                }
            ),
        )
        expected = "ACCOUNTING_ACTION_AFTER_EXIT"
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=instant("2024-05-06T20:00:00Z"),
            fills=fills,
            actions=events,
            costs=costs(),
        )
    assert caught.value.code == expected


@pytest.mark.parametrize("value", [1, False, 0.0])
def test_unsupported_or_coerced_carry_costs_never_become_silent_zero(value: object) -> None:
    """The declared zero-carry scope is strict and rejects unsupported cost profiles."""
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(),
            actions=(),
            costs=costs().model_copy(update={"annual_borrow_bps": value}),
        )
    assert caught.value.code == "ACCOUNTING_INPUT_INVALID"


def test_fixed_decimal_context_and_both_trade_cost_components() -> None:
    """Ambient precision cannot change arithmetic; fees use absolute notional for either side."""
    policy = costs(10).model_copy(update={"slippage_bps": 5})
    with localcontext() as context:
        context.prec = 2
        result = account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(fill("SEC-A", "5"), fill("SEC-B", "-25")),
            actions=(),
            marks=(mark("SEC-A", 0), mark("SEC-B", 0)),
            costs=policy,
        )
    assert result.fees_usd == Decimal("1.5")
    assert result.nav_usd == Decimal("998.5")
    assert result.total_return == Decimal("-0.0015")


@pytest.mark.parametrize(
    "case",
    [
        "zero_cash",
        "negative_cash",
        "nan_cash",
        "tiny_cash",
        "naive",
        "backward",
        "oversized",
        "generator",
    ],
)
def test_invalid_account_boundary_inputs_fail_typed(case: str) -> None:
    """Time, arithmetic and workload limits reject before replay can produce an account."""
    args: dict[str, Any] = dict(
        initial_cash=Decimal(1000), start_at=START, at=START, fills=(), actions=(), costs=costs()
    )
    if case.endswith("cash"):
        args["initial_cash"] = {
            "zero_cash": Decimal(0),
            "negative_cash": Decimal(-1),
            "nan_cash": Decimal("NaN"),
            "tiny_cash": Decimal("1e-1000000"),
        }[case]
    elif case == "naive":
        args["start_at"] = START.replace(tzinfo=None)
    elif case == "backward":
        args["at"] = instant("2024-04-28T20:00:00Z")
    elif case == "oversized":
        args["fills"] = (fill("SEC-A", "10"),) * 2049
    else:
        args["fills"] = iter(())
    with pytest.raises(ResearchError) as caught:
        ledger_at(**args)
    assert caught.value.code == "ACCOUNTING_INPUT_INVALID"


def test_numeric_growth_rejects_before_a_magnitude_exceeds_supported_bounds() -> None:
    """Two individually bounded inputs cannot silently create an unsupported account size."""
    trade = fill("SEC-A", "1e24")
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(trade,),
            actions=(),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_NUMERIC_BOUND"


def test_cash_event_cannot_resurrect_an_already_exited_security() -> None:
    """A late entitlement on a terminal identity requires an explicit new event model."""
    dividend = actions()[1].model_copy(update={"security_id": "SEC-B"})
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=instant("2024-05-06T20:00:00Z"),
            fills=(fill("SEC-B", "50"),),
            actions=(actions()[2], dividend),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_ACTION_AFTER_EXIT"


def test_late_availability_is_retained_but_never_changes_economic_booking_time() -> None:
    """Ex-post accounting is explicitly separate from whether a decision could know an event."""
    action = actions()[2].model_copy(update={"available_at": instant("2024-05-06T20:00:00Z")})
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-02T13:30:00Z"),
        fills=(fill("SEC-B", "50"),),
        actions=(action,),
        marks=(),
        costs=costs(),
    )
    assert result.nav_usd == Decimal(1200)
    assert result.claims[0].signed_amount_usd == Decimal(1200)


def test_zero_terminal_payout_is_known_terms_not_unknown_imputation() -> None:
    """Explicit known zero is distinguishable from the forbidden replacement of a null outcome."""
    event = actions()[2].model_copy(update={"cash_per_share": Decimal(0)})
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-02T16:00:00Z"),
        fills=(fill("SEC-B", "50"),),
        actions=(event,),
        marks=(),
        costs=costs(),
    )
    assert result.nav_usd == 0 and result.total_return == -1


def test_validated_mapping_fill_is_not_read_again_as_an_unvalidated_object() -> None:
    """Pydantic's valid mapping input must have the same safe behavior across both boundaries."""
    raw_fills: Any = (fill("SEC-A", "10").model_dump(),)
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=START,
        fills=raw_fills,
        actions=(),
        marks=(mark("SEC-A", 0),),
        costs=costs(),
    )
    assert result.nav_usd == Decimal(1000)


def test_fold_cannot_make_a_backward_absolute_accounting_window_appear_forward() -> None:
    """Wall-clock ordering cannot override actual UTC event chronology."""
    zone = FoldZone()
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=datetime(2024, 11, 3, 1, 15, tzinfo=zone, fold=1),
            at=datetime(2024, 11, 3, 1, 45, tzinfo=zone, fold=0),
            fills=(),
            actions=(),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_INPUT_INVALID"


def test_utc_conversion_overflow_is_typed_validation_failure() -> None:
    """A supported local date whose UTC instant underflows never escapes as OverflowError."""
    impossible = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14)))
    with pytest.raises(ValidationError):
        PriceMark.model_validate(mark("SEC-A", 0).model_copy(update={"observed_at": impossible}))
    with pytest.raises(ResearchError) as caught:
        ledger_at(
            initial_cash=Decimal(1000),
            start_at=impossible,
            at=START,
            fills=(),
            actions=(),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_INPUT_INVALID"


def test_mutable_default_decimal_context_cannot_change_the_ledger() -> None:
    """Process defaults for exponent bounds and traps cannot affect fixed local arithmetic."""
    original = DefaultContext.copy()
    try:
        DefaultContext.Emax = 1
        DefaultContext.Emin = -1
        result = account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(fill("SEC-A", "10"),),
            actions=(),
            marks=(mark("SEC-A", 0),),
            costs=costs(),
        )
        assert result.nav_usd == Decimal(1000)
    finally:
        DefaultContext.Emax = original.Emax
        DefaultContext.Emin = original.Emin


@pytest.mark.parametrize(
    "case", ["positions", "claims", "phases", "paid_claim", "future_phase", "return"]
)
def test_reloaded_account_rejects_contradictory_inventory_and_return(case: str) -> None:
    """A saved output cannot multiply positions/phases or alter its stated return denominator."""
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=instant("2024-05-03T20:00:00Z"),
        fills=(fill("SEC-A", "10"),),
        actions=actions(),
        marks=(mark("SEC-A", 4),),
        costs=costs(),
    )
    value = result.model_dump(mode="json")
    if case in {"positions", "claims"}:
        value[case].append(value[case][0])
    elif case == "phases":
        value["applied_phases"].append(value["applied_phases"][0])
    elif case == "paid_claim":
        value["claims"][0]["pay_at"] = START.isoformat()
    elif case == "future_phase":
        value["applied_phases"][0]["occurred_at"] = "2024-05-06T20:00:00Z"
    else:
        value["total_return"] = "0.99"
    with pytest.raises(ValidationError):
        LedgerSnapshot.model_validate_json(json.dumps(value))


def test_fill_and_mark_cannot_create_profit_from_conflicting_same_instant_prices() -> None:
    """A different source ID does not authorize a second raw price for the same economic instant."""
    quote = mark("SEC-A", 0).model_copy(
        update={"source_id": "different", "price_usd": Decimal(101)}
    )
    with pytest.raises(ResearchError) as caught:
        account_at(
            initial_cash=Decimal(1000),
            start_at=START,
            at=START,
            fills=(fill("SEC-A", "10"),),
            actions=(),
            marks=(quote,),
            costs=costs(),
        )
    assert caught.value.code == "ACCOUNTING_MARK_CONFLICT"


def test_saved_initial_cash_cannot_bypass_precision_and_escape_as_decimal_overflow() -> None:
    """Reloaded results must preserve the same bounded initial cash admission as fresh replay."""
    result = account_at(
        initial_cash=Decimal(1000),
        start_at=START,
        at=START,
        fills=(),
        actions=(),
        marks=(),
        costs=costs(),
    )
    value = result.model_dump() | {
        "initial_cash_usd": Decimal("1e-1000000"),
        "nav_usd": Decimal(1),
        "total_return": Decimal(0),
    }
    with pytest.raises(ValidationError):
        LedgerSnapshot.model_validate(value)
