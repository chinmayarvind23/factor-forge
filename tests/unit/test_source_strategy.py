"""Source-to-strategy compilation preserves explicit data and execution assumptions."""

from decimal import Decimal

import pytest
from test_monthly_admission import AT, original_strategy

from factorforge.backtests.monthly import run_monthly
from factorforge.domain.extraction import SourceExtraction
from factorforge.factors.source_strategy import SourceStrategyRequest, compile_source_strategy


def request() -> SourceStrategyRequest:
    """An original observation uses the fixture's reviewed monthly formation convention."""
    spec, _ = original_strategy()
    return SourceStrategyRequest(
        environment=spec,
        reviewed_formation_rule="Last session close each month",
        observation=SourceExtraction(
            status="extracted",
            refusal_reason=None,
            refusal_category=None,
            formula="score",
            required_inputs=["score"],
            long_short_direction="long_high_short_low",
            bucket_count=2,
            weighting="equal_weight",
            lookback_months=None,
            holding_months=1,
            rebalance_frequency="monthly",
            formation_lag_months=0,
            formation_rule="Last session close each month",
            source_pages=[1],
        ),
    )


def test_compiled_source_runs_through_actual_monthly_engine() -> None:
    """Compilation supplies a real executable draft with the original oracle unchanged."""
    command = request()
    result = compile_source_strategy(command)
    assert result.strategy is not None and result.reasons == ()
    assert result.request == command
    assert result.strategy.execution_sha256 == command.environment.execution_sha256
    _, store = original_strategy()
    run = run_monthly(result.strategy, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)
    assert run.status == "completed"
    assert run.observations[-1].snapshot.nav_usd == Decimal("1057.98")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("formula", None, "missing_formula"),
        ("required_inputs", ["book_to_market"], "input_binding_mismatch"),
        ("weighting", "value_weight", "unsupported_weighting"),
        ("holding_months", 12, "unsupported_holding_period"),
        ("rebalance_frequency", "annual", "unsupported_rebalance"),
        ("formation_lag_months", None, "missing_formation_lag"),
        ("formation_rule", None, "formation_rule_requires_review"),
        ("formula", "score + unknown", "invalid_strategy_contract"),
        ("formula", "compound_return(score, 12)", "invalid_strategy_contract"),
        ("bucket_count", 10, "invalid_strategy_contract"),
        ("long_short_direction", None, "missing_direction"),
    ],
)
def test_unresolved_observations_remain_explicit(field: str, value: object, reason: str) -> None:
    """Unknown source choices never inherit convenient strategy defaults."""
    command = request()
    observation = command.observation.model_copy(update={field: value})
    result = compile_source_strategy(command.model_copy(update={"observation": observation}))
    assert result.strategy is None and reason in result.reasons
    assert result.request.observation == observation


def test_direction_is_taken_from_source_without_mutating_environment() -> None:
    """Source economics replace draft choices while reviewed data and fee policies stay fixed."""
    command = request()
    observation = command.observation.model_copy(
        update={"long_short_direction": "long_low_short_high"}
    )
    result = compile_source_strategy(command.model_copy(update={"observation": observation}))
    assert result.strategy is not None
    assert result.strategy.portfolio.allocation.direction == "long_low_short_high"
    assert command.environment.portfolio.allocation.direction == "long_high_short_low"
    assert result.strategy.costs == command.environment.costs


def test_refusal_is_retained_without_a_strategy() -> None:
    """A refusal remains a terminal source observation and never becomes an executable draft."""
    command = request()
    fields: dict[str, object] = {key: None for key in command.observation.model_fields_set}
    fields.update(
        status="refused",
        refusal_reason="No supported strategy in these pages",
        refusal_category="insufficient_information",
        required_inputs=[],
        source_pages=[],
    )
    source = SourceExtraction.model_validate(fields)
    result = compile_source_strategy(command.model_copy(update={"observation": source}))
    assert result.strategy is None
    assert "source_refused" in result.reasons
    assert result.request.observation == source
