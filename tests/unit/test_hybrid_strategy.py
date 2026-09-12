"""Hybrid composition preserves explicit economics, units, input meanings and source evidence."""

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_monthly_admission import original_strategy

from factorforge.data.hybrid_fixture import prepare_hybrid_fixture
from factorforge.domain.formula import evaluate_formula
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.targets import Rational
from factorforge.factors.hybrid import HybridComponent, HybridRequest, compile_hybrid


def request() -> HybridRequest:
    """Two distinct source hypotheses have opposite raw orientation on a common scale."""
    first, _ = original_strategy()
    wire = first.model_dump(mode="json")
    wire.update(factor_id="second-original", name="Second original hypothesis", formula="-score")
    wire["portfolio"]["allocation"]["direction"] = "long_low_short_high"
    second = RawStrategySpec.model_validate_json(json.dumps(wire))
    return HybridRequest(
        name="Direction-aligned blend",
        rationale="Combine two explicitly weighted original hypotheses on the same signal scale.",
        components=(
            HybridComponent(strategy=first, weight=Rational.from_fraction(Fraction(3, 4))),
            HybridComponent(strategy=second, weight=Rational.from_fraction(Fraction(1, 4))),
        ),
    )


def test_direction_alignment_and_exact_weights_retain_both_parents() -> None:
    """A low-is-good component is negated before blending; source identity stays inspectable."""
    value = request()
    _, store = original_strategy()
    result = compile_hybrid(value, store)
    assert result.strategy is not None and result.reasons == ()
    assert result.strategy.portfolio.allocation.direction == "long_high_short_low"
    assert evaluate_formula(result.strategy.formula, scalars={"score": "2"}) == Decimal("2")
    assert result.strategy.signal_inputs == value.components[0].strategy.signal_inputs
    assert result.strategy.costs == value.components[0].strategy.costs
    assert all(parent.sha256 in store.values for parent in result.parents)
    assert result.request == value


def test_independent_signals_both_contribute_to_the_composite_score() -> None:
    """The actual two-input example matches hand arithmetic before portfolio ranking."""
    _, store = original_strategy()
    value = prepare_hybrid_fixture(Path(__file__).resolve().parents[2], store)
    draft = compile_hybrid(value, store)
    assert draft.strategy is not None
    assert {binding.name for binding in draft.strategy.signal_inputs} == {"score", "quality"}
    assert evaluate_formula(
        draft.strategy.formula, scalars={"score": "2", "quality": "1"}
    ) == Decimal("1.75")
    assert evaluate_formula(
        draft.strategy.formula, scalars={"score": "1", "quality": "3"}
    ) == Decimal("1.5")


@pytest.mark.parametrize("change", ["costs", "timing", "units", "binding"])
def test_incompatible_component_economics_are_held(change: str) -> None:
    """A blend cannot silently choose one parent's costs, timing or input interpretation."""
    value = request()
    wire = value.model_dump(mode="json")
    second = wire["components"][1]["strategy"]
    if change == "costs":
        second["costs"]["commission_bps"] += 1
    elif change == "timing":
        second["timing"]["formation_lag_months"] += 1
    elif change == "units":
        second["signal_unit"] = "return_decimal"
        second["signal_inputs"][0]["unit"] = "return_decimal"
    else:
        second["signal_inputs"][0]["concept"] = "another_score"
    _, store = original_strategy()
    result = compile_hybrid(HybridRequest.model_validate_json(json.dumps(wire)), store)
    assert result.strategy is None and result.reasons


@pytest.mark.parametrize("weights", [(0, 1), (-1, 2), (1, 1)])
def test_invalid_weight_policy_is_rejected(weights: tuple[int, int]) -> None:
    """The versioned policy requires positive component weights that sum exactly to one."""
    wire = request().model_dump(mode="json")
    for item, weight in zip(wire["components"], weights, strict=True):
        item["weight"] = Rational.from_fraction(Fraction(weight)).model_dump(mode="json")
    with pytest.raises(ValidationError):
        HybridRequest.model_validate_json(json.dumps(wire))
