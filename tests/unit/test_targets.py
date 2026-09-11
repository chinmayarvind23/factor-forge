"""Conditional target weights preserve exact ranks, sleeve normalization and drift turnover."""

import json
from datetime import UTC, datetime
from fractions import Fraction

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import FormationPlan
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import CostSpec, PortfolioSpec
from factorforge.domain.targets import (
    CrossSection,
    PositionWeight,
    Rational,
    SignalValue,
    TargetPlan,
    TradeCost,
)
from factorforge.factors.targets import build_targets, estimate_trade_cost


def portfolio(**changes: object) -> PortfolioSpec:
    """An original conditional policy uses three balanced buckets and pre-trade unit sleeves."""
    return PortfolioSpec.model_validate(
        {
            "direction": "long_high_short_low",
            "bucket_count": 3,
            "bucket_allocation": "balanced_contiguous_low_remainder",
            "weighting": "equal_weight",
            "weight_input": None,
            "breakpoints": "all_eligible",
            "ties": "stable_security_id",
            "minimum_bucket_size": 1,
            "long_exposure": 1,
            "short_exposure": 1,
            "sizing_basis": "pre_trade_nav",
            "short_proceeds": "segregated",
            "cash_return": "zero",
        }
        | changes
    )


def panel() -> CrossSection:
    """Seven authored rows test unequal bucket sizes, exact ties and capitalization weights."""
    return CrossSection(
        source_refs=(ArtifactRef(sha256="a" * 64, size_bytes=1, media_type="application/json"),),
        formation=FormationPlan(
            calendar_sha256="b" * 64,
            formation_at=datetime(2024, 4, 30, 20, tzinfo=UTC),
            trade_at=datetime(2024, 5, 1, 13, 30, tzinfo=UTC),
        ),
        universe=tuple("ABCDEFG"),
        observations=tuple(
            SignalValue(security_id=key, signal=str(signal), capitalization=str(cap))
            for key, signal, cap in zip(
                "ABCDEFG", [1, 1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6, 12], strict=True
            )
        ),
    )


def test_balanced_buckets_preserve_fixed_low_side_remainder_and_unit_sleeves() -> None:
    """Direction changes positions after partitioning; extra rows always belong to low buckets."""
    result = build_targets(panel(), portfolio(), missing_signal="fail")
    assert [(row.security_id, row.bucket) for row in result.positions] == list(
        zip("ABCDEFG", [0, 0, 0, 1, 1, 2, 2], strict=True)
    )
    assert [row.weight.as_fraction() for row in result.positions] == [Fraction(-1, 3)] * 3 + [
        Fraction(0)
    ] * 2 + [Fraction(1, 2)] * 2
    reversed_result = build_targets(
        panel(), portfolio(direction="long_low_short_high"), missing_signal="fail"
    )
    assert [row.weight.as_fraction() for row in reversed_result.positions] == [
        -row.weight.as_fraction() for row in result.positions
    ]


def test_value_weighting_normalizes_each_tail_exactly() -> None:
    """Capitalization weights normalize within each extreme rather than the whole universe."""
    result = build_targets(
        panel(), portfolio(weighting="value_weight", weight_input="cap"), missing_signal="fail"
    )
    assert [row.weight.as_fraction() for row in result.positions] == [
        Fraction(-1, 6),
        Fraction(-1, 3),
        Fraction(-1, 2),
        Fraction(0),
        Fraction(0),
        Fraction(1, 3),
        Fraction(2, 3),
    ]


def test_exact_decimal_order_is_not_collapsed_into_float_ties() -> None:
    """Distinctions finer than Float64 affect order before the stable ID tie-break applies."""
    value = panel()
    rows = list(value.observations)
    rows[0] = rows[0].model_copy(update={"signal": "1.000000000000000000000002"})
    rows[1] = rows[1].model_copy(update={"signal": "1.000000000000000000000001"})
    result = build_targets(
        value.model_copy(update={"observations": tuple(rows)}), portfolio(), missing_signal="fail"
    )
    assert [row.security_id for row in result.positions][:2] == ["B", "A"]


@pytest.mark.parametrize("kind", ["absent", "signal", "cap"])
def test_missing_inputs_follow_declared_policy_before_partitioning(kind: str) -> None:
    """Missing rows produce exclusions or failures, never zero signals or weighting repairs."""
    value = panel()
    rows = list(value.observations)
    rule = portfolio()
    if kind == "absent":
        rows.pop()
    elif kind == "signal":
        rows[-1] = rows[-1].model_copy(update={"signal": None})
    else:
        rows[-1] = rows[-1].model_copy(update={"capitalization": None})
        rule = portfolio(weighting="value_weight", weight_input="cap")
    value = value.model_copy(update={"observations": tuple(rows)})
    with pytest.raises(ResearchError):
        build_targets(value, rule, missing_signal="fail")
    result = build_targets(value, rule, missing_signal="exclude_at_formation")
    assert result.excluded == ("G",) and len(result.positions) == 6
    assert [row.bucket for row in result.positions] == [0, 0, 1, 1, 2, 2]


def test_insufficient_bucket_sizes_fail_without_reducing_bucket_count() -> None:
    """The declared minimum is enforced across all buckets after exclusions."""
    with pytest.raises(ResearchError):
        build_targets(panel(), portfolio(minimum_bucket_size=3), missing_signal="fail")


def test_trade_cost_uses_drifted_weights_and_liquidates_removed_security() -> None:
    """Target-zero absent holdings still create turnover and cannot be dropped from the fee base."""
    targets = build_targets(panel(), portfolio(), missing_signal="fail")
    drifted = tuple(
        PositionWeight(security_id=key, weight=Rational.from_fraction(weight))
        for key, weight in [("A", Fraction(-1, 2)), ("F", Fraction(3, 4)), ("X", Fraction(1, 4))]
    )
    costs = CostSpec(
        commission_bps=10,
        slippage_bps=5,
        borrow_bps_annual=100,
        financing_bps_annual=200,
        turnover="absolute_change_from_drifted_weights",
        charge="all_trades",
        day_count="actual_365",
    )
    result = estimate_trade_cost(targets, drifted, costs)
    assert result.turnover.as_fraction() == Fraction(11, 6)
    assert result.commission.as_fraction() == Fraction(11, 6000)
    assert result.slippage.as_fraction() == Fraction(11, 12000)


@pytest.mark.parametrize(
    "numerator,denominator", [("2", "4"), ("0", "2"), ("1", "0"), ("01", "2"), ("1", "-1")]
)
def test_rationals_require_canonical_reduced_components(numerator: str, denominator: str) -> None:
    """Equivalent encodings cannot manufacture different target identities."""
    with pytest.raises(ValidationError):
        Rational(numerator=numerator, denominator=denominator)


@pytest.mark.parametrize(
    "field,value",
    [("signal", "NaN"), ("signal", "1e101"), ("capitalization", "0"), ("capitalization", "-1")],
)
def test_bad_values_are_rejected_before_any_exclusion(field: str, value: str) -> None:
    """Malformed numeric data is not a missing observation, even outside the eligible inventory."""
    rows = (
        *panel().observations,
        SignalValue.model_construct(security_id="X", signal="1", capitalization="1").model_copy(
            update={field: value}
        ),
    )
    with pytest.raises(ResearchError):
        build_targets(
            panel().model_copy(update={"observations": rows}),
            portfolio(),
            missing_signal="exclude_at_formation",
        )


@pytest.mark.parametrize(
    "case", ["duplicate_universe", "duplicate_rows", "bad_policy", "empty", "exponent"]
)
def test_inventory_and_policy_errors_fail_before_target_production(case: str) -> None:
    """Target creation cannot silently merge conflicting IDs or admit an unknown missing policy."""
    value = panel()
    if case == "duplicate_universe":
        value = value.model_copy(update={"universe": (*value.universe, "A")})
    elif case == "duplicate_rows":
        value = value.model_copy(
            update={"observations": (*value.observations, value.observations[0])}
        )
    elif case == "empty":
        value = value.model_copy(update={"observations": ()})
    elif case == "exponent":
        rows = list(value.observations)
        rows[0] = rows[0].model_copy(update={"signal": "1e9999999999999999999999999999999"})
        value = value.model_copy(update={"observations": tuple(rows)})
    with pytest.raises(ResearchError):
        if case == "bad_policy":
            build_targets(value, portfolio(), missing_signal="guess")  # type: ignore[arg-type]
        else:
            build_targets(value, portfolio(), missing_signal="exclude_at_formation")


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "duplicate",
        "bucket",
        "minimum",
        "interior",
        "equal_weights",
        "unit_total",
        "excluded",
    ],
)
def test_saved_targets_reject_contradictions(case: str) -> None:
    """Tampering with a saved target plan cannot preserve its declared arithmetic contract."""
    result = build_targets(panel(), portfolio(), missing_signal="fail")
    value = result.model_dump(mode="json")
    if case == "hash":
        value["portfolio_sha256"] = "f" * 64
    elif case == "duplicate":
        value["positions"][1]["security_id"] = "A"
    elif case == "bucket":
        value["positions"][0]["bucket"] = 2
    elif case == "minimum":
        value["portfolio"]["minimum_bucket_size"] = 3
        value["portfolio_sha256"] = portfolio(minimum_bucket_size=3).sha256
    elif case == "interior":
        value["positions"][3]["weight"] = {"numerator": "1", "denominator": "2"}
    elif case == "equal_weights":
        value["positions"][-1]["weight"] = {"numerator": "1", "denominator": "3"}
        value["positions"][-2]["weight"] = {"numerator": "2", "denominator": "3"}
    elif case == "unit_total":
        value["portfolio"] = portfolio(weighting="value_weight", weight_input="cap").model_dump(
            mode="json"
        )
        value["portfolio_sha256"] = portfolio(weighting="value_weight", weight_input="cap").sha256
        value["positions"][-1]["weight"] = {"numerator": "1", "denominator": "3"}
    else:
        value["excluded"] = ["A"]
    with pytest.raises(ValidationError):
        TargetPlan.model_validate_json(json.dumps(value))


def test_cost_inventory_and_saved_math_are_revalidated() -> None:
    """Duplicate drift positions and altered cost output cannot hide liquidation turnover."""
    result = build_targets(panel(), portfolio(), missing_signal="fail")
    costs = CostSpec(
        commission_bps=10,
        slippage_bps=0,
        borrow_bps_annual=0,
        financing_bps_annual=0,
        turnover="absolute_change_from_drifted_weights",
        charge="all_trades",
        day_count="actual_365",
    )
    position = PositionWeight(security_id="A", weight=Rational.from_fraction(Fraction(1)))
    for drifted in ((position, position), (position,) * 10001):
        with pytest.raises(ResearchError):
            estimate_trade_cost(result, drifted, costs)
    estimate = estimate_trade_cost(result, (), costs)
    assert estimate.turnover.as_fraction() == 2
    with pytest.raises(ValidationError):
        TradeCost.model_validate(
            estimate.model_copy(update={"commission": Rational.from_fraction(Fraction(0))})
        )


def test_fraction_growth_bound_prevents_unbounded_exact_arithmetic() -> None:
    """Precision limits apply before serialization of adversarial denominator growth."""
    with pytest.raises(ValueError):
        Rational.from_fraction(Fraction(1, 2**2049))


def test_input_order_does_not_change_conditional_targets_or_lineage_identity() -> None:
    """Canonical selected inventory order preserves a reproducible conditional target result."""
    value = panel()
    first = build_targets(value, portfolio(), missing_signal="fail")
    second = build_targets(
        value.model_copy(
            update={
                "universe": tuple(reversed(value.universe)),
                "observations": tuple(reversed(value.observations)),
            }
        ),
        portfolio(),
        missing_signal="fail",
    )
    assert first == second
