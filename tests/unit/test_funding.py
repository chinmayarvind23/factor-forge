"""Original exact hand amounts test funding arithmetic without strategy or quote admission."""

from decimal import Decimal, DefaultContext, localcontext
from fractions import Fraction

import pytest
from pydantic import ValidationError

from factorforge.backtests.funding import (
    CollateralObservation,
    FundingPlan,
    FundingRequest,
    SignedNotional,
    exact_accounting,
    exact_quantity,
    observe_collateral,
    solve_post_fee,
)
from factorforge.domain.accounting import LedgerCosts
from factorforge.domain.errors import ResearchError
from factorforge.domain.targets import PositionWeight, Rational


def rational(value: str | int | Fraction) -> Rational:
    """Convert small authored test numbers to the existing exact rational wire contract."""
    return Rational.from_fraction(Fraction(value))


def notional(security: str, value: str | int | Fraction) -> SignedNotional:
    """Bind a hand-derived signed market value to one permanent fixture ID."""
    return SignedNotional(security_id=security, notional_usd=rational(value))


def request(
    nav: int = 1002, *, old: tuple[SignedNotional, ...] = (), bps: int = 10
) -> FundingRequest:
    """The original unit long/short request has explicit zero carry and a cash trade fee."""
    return FundingRequest(
        pre_trade_nav_usd=rational(nav),
        old_notionals=old,
        target_weights=(
            PositionWeight(security_id="A", weight=rational(1)),
            PositionWeight(security_id="B", weight=rational(-1)),
        ),
        costs=LedgerCosts(
            commission_bps=bps,
            slippage_bps=0,
            annual_borrow_bps=0,
            annual_financing_bps=0,
            annual_interest_bps=0,
        ),
        purpose="rebalance",
    )


def test_fresh_positive_fee_root_is_exact_and_separate_from_quantity_admission() -> None:
    """1002 of equity funds two 1000 sleeves and exactly two dollars of entry fees."""
    result = solve_post_fee(request())
    assert result.sizing_nav_usd.as_fraction() == 1000
    assert result.absolute_trade_notional_usd.as_fraction() == 2000
    assert result.commission_usd.as_fraction() == 2
    assert result.slippage_usd.as_fraction() == 0
    assert result.scope == "pure-post-fee-notional-solution"
    assert result.request_sha256 == result.request.sha256
    assert FundingPlan.model_validate_json(result.model_dump_json()) == result


def test_repeating_root_is_solved_but_quantity_conversion_rejects() -> None:
    """A financially funded rational notional is not automatically a ledger-representable fill."""
    result = solve_post_fee(request(1000))
    assert result.sizing_nav_usd.as_fraction() == Fraction(500000, 501)
    with pytest.raises(ResearchError, match="supported exact precision"):
        exact_quantity(result.sizing_nav_usd.as_fraction() / 100)


def test_piecewise_drift_root_has_hand_calculated_fee() -> None:
    """The root must use actual drifted signed notionals rather than another entry-only formula."""
    result = solve_post_fee(request(1400, old=(notional("A", 1200), notional("B", -800))))
    assert result.sizing_nav_usd.as_fraction() == Fraction(701000, 501)
    assert result.commission_usd.as_fraction() == Fraction(400, 501)
    assert [row.trade_notional_usd.as_fraction() for row in result.positions] == [
        Fraction(99800, 501),
        -Fraction(300200, 501),
    ]


def test_breakpoint_and_zero_fee_roots_preserve_no_trade() -> None:
    """Exact equality at a kink is admitted without iterative numerical tolerance."""
    old = (notional("A", 1000), notional("B", -1000))
    result = solve_post_fee(request(1000, old=old))
    assert result.sizing_nav_usd.as_fraction() == 1000
    assert result.absolute_trade_notional_usd.as_fraction() == 0
    assert solve_post_fee(request(1000, bps=0)).sizing_nav_usd.as_fraction() == 1000


def test_terminal_liquidation_charges_all_signed_positions() -> None:
    """Liquidation has no replacement sleeve and includes both sale and cover fees."""
    value = request(1060, old=(notional("A", 1040), notional("B", -980)))
    value = value.model_copy(update={"purpose": "liquidate", "target_weights": ()})
    result = solve_post_fee(value)
    assert result.sizing_nav_usd.as_fraction() == Fraction("1057.98")
    assert result.absolute_trade_notional_usd.as_fraction() == 2020
    assert result.commission_usd.as_fraction() == Fraction("2.02")


@pytest.mark.parametrize("bps", [5000, 5001, 10000])
def test_slope_gate_prevents_nonmonotone_or_flat_unsupported_equations(bps: int) -> None:
    """The sufficient uniqueness condition remains a strict precondition."""
    with pytest.raises(ResearchError) as error:
        solve_post_fee(request(bps=bps))
    assert error.value.code == "FUNDING_SLOPE_UNSUPPORTED"


@pytest.mark.parametrize("nav", [1, 2])
def test_liquidation_cost_can_make_positive_root_infeasible(nav: int) -> None:
    """E no greater than the existing positions' liquidation fee admits no positive x."""
    with pytest.raises(ResearchError) as error:
        solve_post_fee(request(nav, old=(notional("A", 1000), notional("B", -1000))))
    assert error.value.code == "FUNDING_LIQUIDATION_INFEASIBLE"


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(10), "10"),
        (Fraction(1, 8), "0.125"),
        (Fraction(-1, 10**18), "-0.000000000000000001"),
        (Fraction(0), "0"),
    ],
)
def test_exact_quantity_conversion_never_rounds(value: Fraction, expected: str) -> None:
    """Terminating bounded signed quantities reproduce their exact rational input."""
    assert exact_quantity(value) == Decimal(expected)


@pytest.mark.parametrize("value", [Fraction(1, 3), Fraction(1, 10**19), Fraction(10**24 + 1)])
def test_quantity_conversion_refuses_precision_or_magnitude_loss(value: Fraction) -> None:
    """Unsupported quantities fail explicitly instead of being truncated into an executable fill."""
    with pytest.raises(ResearchError):
        exact_quantity(value)


def test_accounting_precision_is_separate_from_fill_precision() -> None:
    """Exact fifty-digit accounting can retain a terminating value too fine for ledger input."""
    value = Fraction(1, 10**30)
    assert exact_accounting(value) == Decimal("1e-30")
    with pytest.raises(ResearchError):
        exact_quantity(value)
    with pytest.raises(ResearchError):
        exact_accounting(Fraction(10**50 + 1, 10**50))


def test_failed_collateral_observation_remains_inspectable() -> None:
    """Positive NAV with a short collateral deficit is retained evidence of funding failure."""
    result = observe_collateral(
        cash_usd=Decimal(1000), notionals=(notional("A", 1000), notional("B", -1010))
    )
    assert result.nav_usd.as_fraction() == 990
    assert result.restricted_cash_usd.as_fraction() == 1010
    assert result.free_cash_usd.as_fraction() == -10
    assert result.status == "unfunded"
    assert result.failure_code == "FUNDING_COLLATERAL_DEFICIT"


def test_copied_plan_cannot_forge_its_root_or_identity() -> None:
    """Saved outputs recheck exact arithmetic and canonical request identity."""
    result = solve_post_fee(request())
    for changes in ({"sizing_nav_usd": rational(999)}, {"request_sha256": "a" * 64}):
        with pytest.raises(ValidationError):
            result.model_copy(update=changes).canonical_bytes()


@pytest.mark.parametrize(
    "attribute,value",
    [("_numerator", "1"), ("_denominator", 0), ("_denominator", -1), ("_numerator", True)],
)
def test_forged_fraction_internals_fail_typed_before_arithmetic(
    attribute: str, value: object
) -> None:
    """An exact Fraction instance can still be corrupted through object-level attribute writes."""
    number = Fraction(1)
    object.__setattr__(number, attribute, value)
    for convert in (exact_quantity, exact_accounting):
        with pytest.raises(ResearchError):
            convert(number)


def test_unreduced_fraction_mutation_cannot_change_numeric_identity() -> None:
    """A forged Fraction bypassing normalization cannot enter arithmetic under two encodings."""
    value = Fraction(1)
    object.__setattr__(value, "_numerator", 2)
    object.__setattr__(value, "_denominator", 2)
    with pytest.raises(ResearchError):
        exact_accounting(value)


@pytest.mark.parametrize(
    "value", [1, True, "1", Decimal(1), None, Fraction(1 << 2049), Fraction(1, 1 << 2049)]
)
def test_public_fraction_inputs_are_checked_before_conversion(value: object) -> None:
    """Unexpected types and huge numerator/denominator integers cannot enter conversion loops."""
    with pytest.raises(ResearchError):
        exact_quantity(value)  # type: ignore[arg-type]


def test_decimal_conversion_checks_scale_work_before_powers() -> None:
    """A bounded but pathological power-of-two denominator cannot allocate a huge coefficient."""
    with pytest.raises(ResearchError) as error:
        exact_accounting(Fraction(1, 2**2000))
    assert error.value.code == "FUNDING_ACCOUNTING_PRECISION"


def test_cumulative_exact_arithmetic_has_a_bounded_failure() -> None:
    """Individually valid rational inputs may exceed the declared intermediate bit budget."""
    epsilon = Fraction(1, 10**500 - 3)
    value = request(old=(notional("A", Fraction(1, 10**500 - 1)),))
    value = value.model_copy(
        update={
            "target_weights": (
                PositionWeight(security_id="A", weight=rational(epsilon)),
                PositionWeight(security_id="B", weight=rational(-1)),
                PositionWeight(security_id="C", weight=rational(1 - epsilon)),
            )
        }
    )
    with pytest.raises(ResearchError) as error:
        solve_post_fee(value)
    assert error.value.code == "FUNDING_NUMERIC_BOUND"


def test_root_serialization_refuses_components_beyond_rational_wire_budget() -> None:
    """A finite bounded calculation cannot emit a result outside the existing wire schema."""
    value = request(old=(notional("C", Fraction(1, 10**510 + 1)),))
    with pytest.raises(ResearchError) as error:
        solve_post_fee(value)
    assert error.value.code == "FUNDING_NUMERIC_BOUND"


@pytest.mark.parametrize(
    "kind",
    [
        "zero_nav",
        "negative_nav",
        "duplicate_old",
        "duplicate_target",
        "mutable_old",
        "too_many",
        "union",
        "bad_sleeves",
        "nonzero_liquidation",
        "forged_cost",
    ],
)
def test_forged_requests_fail_before_solving(kind: str) -> None:
    """Copied input objects cannot evade bounds, uniqueness, purpose or explicit zero carry."""
    value = request()
    changes: dict[str, object]
    if kind == "zero_nav":
        changes = {"pre_trade_nav_usd": rational(0)}
    elif kind == "negative_nav":
        changes = {"pre_trade_nav_usd": rational(-1)}
    elif kind == "duplicate_old":
        changes = {"old_notionals": (notional("A", 1), notional("A", 2))}
    elif kind == "duplicate_target":
        changes = {"target_weights": value.target_weights * 2}
    elif kind == "mutable_old":
        changes = {"old_notionals": []}
    elif kind == "too_many":
        changes = {"old_notionals": (notional("A", 1),) * 9}
    elif kind == "union":
        changes = {"old_notionals": tuple(notional(str(index), 1) for index in range(8))}
    elif kind == "bad_sleeves":
        changes = {"target_weights": value.target_weights[:1]}
    elif kind == "nonzero_liquidation":
        changes = {"purpose": "liquidate"}
    else:
        changes = {"costs": value.costs.model_copy(update={"annual_borrow_bps": 1})}
    with pytest.raises(ResearchError):
        solve_post_fee(value.model_copy(update=changes))


def test_inventory_permutation_has_one_canonical_identity() -> None:
    """Reordering declared positions cannot create a distinct funding operation."""
    value = request(1400, old=(notional("A", 1200), notional("B", -800)))
    changed = value.model_copy(
        update={
            "old_notionals": tuple(reversed(value.old_notionals)),
            "target_weights": tuple(reversed(value.target_weights)),
        }
    )
    assert solve_post_fee(value) == solve_post_fee(changed)


def test_new_security_inventory_liquidates_absent_targets_and_splits_costs() -> None:
    """Zero target weights retain complete disposal rather than dropping prior holdings."""
    value = request(1000, old=(notional("C", 1000), notional("D", -1000)), bps=6)
    value = value.model_copy(update={"costs": value.costs.model_copy(update={"slippage_bps": 4})})
    result = solve_post_fee(value)
    assert result.sizing_nav_usd.as_fraction() == Fraction(499000, 501)
    assert [row.security_id for row in result.positions] == list("ABCD")
    assert [row.trade_notional_usd.as_fraction() for row in result.positions[2:]] == [-1000, 1000]
    assert result.commission_usd.as_fraction() / result.slippage_usd.as_fraction() == Fraction(3, 2)


def test_short_direction_reversal_and_zero_template_rows_are_explicit() -> None:
    """Crossing zero changes the absolute trade branch and retains an interior zero target."""
    value = request(1000, old=(notional("A", -500), notional("B", 500)))
    value = value.model_copy(
        update={
            "target_weights": (
                *value.target_weights,
                PositionWeight(security_id="C", weight=rational(0)),
            )
        }
    )
    result = solve_post_fee(value)
    assert result.sizing_nav_usd.as_fraction() == Fraction(166500, 167)
    assert result.positions[-1].trade_notional_usd.as_fraction() == 0


@pytest.mark.parametrize(
    "cash,positions,status,nav,free",
    [
        ("1000", (notional("A", 1000), notional("B", -1000)), "funded", 1000, 0),
        ("1000", (notional("A", 1000), notional("B", -2000)), "insolvent", 0, -1000),
        ("1057.98", (), "funded", Fraction("1057.98"), Fraction("1057.98")),
    ],
)
def test_collateral_status_matches_exact_observed_values(
    cash: str,
    positions: tuple[SignedNotional, ...],
    status: str,
    nav: int | Fraction,
    free: int | Fraction,
) -> None:
    """Funded, insolvent and terminal-flat observations remain complete canonical records."""
    value = observe_collateral(cash_usd=Decimal(cash), notionals=positions)
    assert value.status == status and value.nav_usd.as_fraction() == nav
    assert value.free_cash_usd.as_fraction() == free
    assert CollateralObservation.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "cash",
    [
        1,
        True,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e999999999"),
        Decimal("0e999999999"),
        Decimal("1" * 51),
        Decimal("1e25"),
    ],
)
def test_cash_conversion_rejects_bad_shape_before_fraction_allocation(cash: object) -> None:
    """Decimal exponent, finiteness and coefficient checks precede conversion work."""
    with pytest.raises(ResearchError):
        observe_collateral(cash_usd=cash, notionals=())  # type: ignore[arg-type]


def test_collateral_duplicates_and_forged_status_cannot_pass() -> None:
    """A recorded reserve cannot ignore a second identity or rewrite an observed deficit."""
    with pytest.raises(ResearchError):
        observe_collateral(cash_usd=Decimal(1), notionals=(notional("A", 1), notional("A", 1)))
    value = observe_collateral(cash_usd=Decimal(1000), notionals=(notional("B", -1010),))
    with pytest.raises(ValidationError):
        value.model_copy(update={"status": "funded", "failure_code": None}).canonical_bytes()


def test_process_decimal_context_cannot_round_roots_or_conversions() -> None:
    """Mutable default and thread-local Decimal contexts cannot alter exact Fraction arithmetic."""
    before = DefaultContext.copy()
    try:
        DefaultContext.prec = 2
        DefaultContext.Emax = 2
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            assert solve_post_fee(request()).sizing_nav_usd.as_fraction() == 1000
            assert exact_quantity(Fraction(1, 8)) == Decimal("0.125")
            assert exact_accounting(Fraction(123456789, 1000)) == Decimal("123456.789")
    finally:
        DefaultContext.prec = before.prec
        DefaultContext.Emax = before.Emax


@pytest.mark.parametrize("slot", ["_numerator", "_denominator"])
@pytest.mark.parametrize("convert", [exact_quantity, exact_accounting])
def test_deleted_fraction_slots_fail_with_typed_input_error(slot: str, convert: object) -> None:
    """A damaged standard Fraction cannot leak property AttributeError from public conversion."""
    value = Fraction(1)
    object.__delattr__(value, slot)
    with pytest.raises(ResearchError) as caught:
        convert(value)  # type: ignore[operator]
    assert caught.value.code == "FUNDING_INPUT_INVALID"
