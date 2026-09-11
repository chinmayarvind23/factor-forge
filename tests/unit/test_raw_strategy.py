"""Complete original raw-price declarations reject incompatible v2 and unsupported policies."""

from datetime import date

import pytest
from pydantic import ValidationError
from test_experiments import ref
from test_targets import portfolio

from factorforge.domain.accounting import LedgerCosts
from factorforge.domain.factors import AllocationSpec, DatasetLink, TableReference
from factorforge.domain.raw_strategy import (
    IntervalBinding,
    MonthlyInput,
    MonthlyUniverse,
    RawEvaluation,
    RawMarketBinding,
    RawPolicies,
    RawPortfolio,
    RawStrategySpec,
    RawTiming,
)


def table(name: str, schema: str) -> TableReference:
    """Declared identities are valid metadata; schema tests do not pretend to load their bytes."""
    return TableReference(
        dataset_version=ref(b"manifest").sha256,
        object_name=name,
        schema_version=schema,
        artifact=ref(name.encode()),
    )


def strategy() -> RawStrategySpec:
    """The original monthly scalar policy has all explicit supported execution assumptions."""
    monthly = table("monthly", "monthly-source-v1")
    intervals = table("intervals", "interval-returns-v1")
    return RawStrategySpec(
        schema_version="factor-spec-v3",
        profile="monthly-raw-price-post-fee-v1",
        factor_id="original-ratio",
        version="v1",
        name="Original monthly ratio",
        source_refs=(ref(b"original author decisions"),),
        datasets=(DatasetLink(version_id=monthly.dataset_version, manifest=ref(b"manifest")),),
        signal_inputs=(
            MonthlyInput(
                name="signal",
                table=monthly,
                concept="original_signal",
                value_field="value",
                unit="dimensionless",
                frequency="monthly",
                period_context="instant",
                security_id_field="security_id",
                available_at_field="available_at",
                period_end_field="period_end",
                period_start_field=None,
                revision_field="revision",
                revision_policy="latest_available_then_revision_reject_conflicts",
                history_observations=1,
            ),
        ),
        formula="signal",
        signal_unit="dimensionless",
        universe=MonthlyUniverse(
            table=monthly,
            security_id_namespace="original-security-v1",
            security_id_field="security_id",
            included_field="included",
            effective_at_field="effective_at",
            available_at_field="available_at",
            policy="known_effective_events",
            eligibility="historical_membership_only",
        ),
        timing=RawTiming(
            calendar=ref(b"calendar"),
            calendar_id="original-calendar",
            timezone="UTC",
            formation="session_close",
            trade="subsequent_session_open",
            trade_delay_sessions=1,
            rebalance="monthly_last_session",
            lookback_months=None,
            formation_lag_months=0,
            holding_months=1,
            vintage_allocation="nonoverlapping",
            within_cohort="buy_and_hold",
        ),
        portfolio=RawPortfolio(
            allocation=AllocationSpec.model_validate(
                portfolio().model_dump(include=set(AllocationSpec.model_fields))
            ),
            long_exposure=1,
            short_exposure=1,
            sizing_basis="post_fee_nav",
            collateral="current_short_liability_cash_reserve_v1",
            quantity="exact_terminating_decimal_18_v1",
            cash_return="zero",
        ),
        costs=LedgerCosts(
            commission_bps=10,
            slippage_bps=0,
            annual_borrow_bps=0,
            annual_financing_bps=0,
            annual_interest_bps=0,
        ),
        policies=RawPolicies(
            dataset_kind="original_fixture",
            missing_signal="fail",
            missing_price="fail",
            unknown_terminal="fail",
            corporate_actions="reject_any_events",
            point_in_time="available_at_lte_formation_lt_trade",
            freshness="explicit_requested_calendar_month_no_stale_fallback_v1",
            short_loan="require_valid_finite_original_grant",
            funding_failure="stop_run",
            execution="simultaneous_exact_quote_batch",
            fee_charge="all_absolute_trade_notional",
            slippage="cash_charge_at_reference_quote",
            winsorization="none",
            standardization="none",
            neutralization="none",
        ),
        market=RawMarketBinding(
            table=table("market", "raw-market-source-v1"),
            quotes_field="quotes",
            actions_field="actions",
            borrow_grants_field="borrow_grants",
        ),
        evaluation=RawEvaluation(
            benchmark=IntervalBinding(
                table=intervals,
                series_id="benchmark",
                rows_field="rows",
                source_id_field="source_id",
                series_id_field="series_id",
                start_at_field="start_at",
                end_at_field="end_at",
                available_at_field="available_at",
                value_field="cumulative_return",
                unit="return_decimal",
                interval="exact_cumulative_close_to_close",
            ),
            risk_free=IntervalBinding(
                table=intervals,
                series_id="risk_free",
                rows_field="rows",
                source_id_field="source_id",
                series_id_field="series_id",
                start_at_field="start_at",
                end_at_field="end_at",
                available_at_field="available_at",
                value_field="cumulative_return",
                unit="return_decimal",
                interval="exact_cumulative_close_to_close",
            ),
            sample_start=date(2024, 4, 30),
            sample_end=date(2024, 5, 3),
            baseline="sample_start_first_formation_close_initial_cash",
            sample_end_policy="liquidate_at_last_session_with_costs",
            drawdown_observations="baseline_and_session_closes",
            metrics=("net_mean", "net_sharpe", "max_drawdown", "turnover"),
            annualization=252,
        ),
    )


def test_v3_roundtrip_has_no_total_return_or_authored_formation_placeholder() -> None:
    """Raw prices and generated calendar scheduling belong to a distinct complete declaration."""
    value = strategy()
    assert RawStrategySpec.model_validate_json(value.canonical_bytes()) == value
    assert "returns" not in value.model_dump()
    assert value.profile == "monthly-raw-price-post-fee-v1"
    assert value.required_coverage()[value.datasets[0].version_id] == date(2024, 4, 1)


@pytest.mark.parametrize(
    "field,changed",
    [
        ("sizing_basis", "pre_trade_nav"),
        ("collateral", "historical_proceeds"),
        ("quantity", "round_to_nearest"),
        ("long_exposure", True),
        ("short_exposure", 1.0),
        ("cash_return", "interest"),
    ],
)
def test_portfolio_rejects_implicit_or_unsupported_execution_choices(
    field: str, changed: object
) -> None:
    """Fixed policies and strict unit exposures reject v2 and Boolean choices."""
    value = strategy().portfolio.model_dump()
    value[field] = changed
    with pytest.raises(ValidationError):
        RawPortfolio.model_validate(value)


@pytest.mark.parametrize(
    "field,changed",
    [
        ("rebalance", "annual_june_last_session"),
        ("trade_delay_sessions", 2),
        ("trade_delay_sessions", True),
        ("holding_months", 2),
        ("vintage_allocation", "equal_weight_active"),
    ],
)
def test_timing_profile_is_monthly_single_delay_and_nonoverlapping(
    field: str, changed: object
) -> None:
    """Unsupported timing cannot be reduced to the available first monthly executor."""
    value = strategy().timing.model_dump()
    value[field] = changed
    with pytest.raises(ValidationError):
        RawTiming.model_validate(value)


@pytest.mark.parametrize(
    "field,changed",
    [
        ("value_field", "signal"),
        ("available_at_field", "period_end"),
        ("frequency", "annual"),
        ("period_context", "duration"),
        ("revision_field", None),
    ],
)
def test_monthly_mapping_names_actual_source_roles(field: str, changed: object) -> None:
    """A concept name cannot be mistaken for a wide-table value column or publication clock."""
    value = strategy().signal_inputs[0].model_dump()
    value[field] = changed
    with pytest.raises(ValidationError):
        MonthlyInput.model_validate(value)


@pytest.mark.parametrize(
    "formula",
    [
        "missing",
        "signal + assets",
        "delta(signal)",
        "compound_return(signal, 2)",
        "__import__('os')",
    ],
)
def test_formula_closure_and_monthly_operators_are_validated(formula: str) -> None:
    """Names and history semantics close over actual monthly bindings without annual inference."""
    with pytest.raises(ValidationError):
        RawStrategySpec.model_validate(strategy().model_copy(update={"formula": formula}))


def test_decimal_literal_execution_identity_preserves_exact_financial_choices() -> None:
    """AST float rounding cannot deduplicate formulas with distinct exact decimal literals."""
    value = strategy()
    first = value.model_copy(update={"formula": "signal + 0.100000000000000000000001"})
    second = value.model_copy(update={"formula": "signal + 0.100000000000000000000002"})
    assert first.execution_sha256 != second.execution_sha256
    assert (
        value.execution_sha256
        == value.model_copy(
            update={"name": "Another label", "formula": "  signal  "}
        ).execution_sha256
    )


def test_metric_request_order_does_not_change_execution_identity() -> None:
    """Reporting order remains in canonical bytes but cannot duplicate the same computation."""
    value = strategy()
    reordered = value.model_copy(
        update={
            "evaluation": value.evaluation.model_copy(
                update={"metrics": tuple(reversed(value.evaluation.metrics))}
            )
        }
    )
    assert value.sha256 != reordered.sha256
    assert value.execution_sha256 == reordered.execution_sha256


def test_dataset_versions_and_table_schemas_must_close() -> None:
    """Every table references an exactly declared dataset with the actual supported wire schema."""
    value = strategy()
    with pytest.raises(ValidationError):
        value.model_copy(update={"datasets": ()}).canonical_bytes()
    invalid = value.market.model_copy(
        update={
            "table": value.market.table.model_copy(update={"schema_version": "total-returns-v1"})
        }
    )
    with pytest.raises(ValidationError):
        value.model_copy(update={"market": invalid}).canonical_bytes()


def test_evaluation_rejects_hac_and_generic_daily_or_reversed_intervals() -> None:
    """Only implemented metrics and exact interval-return roles can enter this execution profile."""
    value = strategy().evaluation
    for changes in (
        {"metrics": ("hac_tstat",)},
        {"sample_end": date(2024, 4, 29)},
        {"baseline": "caller_supplied_open"},
    ):
        with pytest.raises(ValidationError):
            value.model_copy(update=changes).canonical_bytes()
    with pytest.raises(ValidationError):
        value.risk_free.model_copy(update={"interval": "daily_return"}).canonical_bytes()


def test_compounded_monthly_history_has_explicit_units_window_and_warmup() -> None:
    """Consecutive monthly return history projects without inventing annual observations."""
    value = strategy()
    binding = value.signal_inputs[0].model_copy(
        update={"unit": "return_decimal", "history_observations": 3}
    )
    value = RawStrategySpec.model_validate(
        value.model_copy(
            update={
                "signal_inputs": (binding,),
                "formula": "compound_return(signal, 3)",
                "signal_unit": "return_decimal",
                "timing": value.timing.model_copy(update={"lookback_months": 3}),
            }
        )
    )
    assert value.required_coverage()[value.datasets[0].version_id] == date(2024, 2, 1)
    assert binding.monthly_binding().concept == "original_signal"
    assert binding.monthly_binding().history_observations == 3
    assert len(value.table_references()) == 5
    refs = value.unique_artifacts()
    assert len(refs) == 6
    assert [ref.sha256 for ref in refs] == sorted(ref.sha256 for ref in refs)
    assert len(value.execution_sha256) == 64


@pytest.mark.parametrize("history,lookback", [(1, 3), (3, None), (3, 2)])
def test_compound_requires_both_binding_history_and_timing_window(
    history: int, lookback: int | None
) -> None:
    """A declared operator cannot acquire unrequested observations through an implicit lookback."""
    value = strategy()
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "signal_inputs": (
                    value.signal_inputs[0].model_copy(
                        update={"unit": "return_decimal", "history_observations": history}
                    ),
                ),
                "formula": "compound_return(signal, 3)",
                "signal_unit": "return_decimal",
                "timing": value.timing.model_copy(update={"lookback_months": lookback}),
            }
        ).canonical_bytes()


def test_formula_dimension_mismatch_cannot_be_relabelled() -> None:
    """The existing dimensional grammar remains a schema gate for raw-price strategies."""
    value = strategy()
    with pytest.raises(ValidationError):
        value.model_copy(update={"signal_unit": "USD"}).canonical_bytes()


@pytest.mark.parametrize("role", ["monthly", "interval", "selector"])
def test_shared_bundle_and_series_roles_cannot_hide_unused_sources(role: str) -> None:
    """This first capability reads one monthly bundle and one comparison bundle by explicit role."""
    value = strategy()
    if role == "monthly":
        value = value.model_copy(
            update={
                "signal_inputs": (
                    value.signal_inputs[0].model_copy(
                        update={"table": table("other", "monthly-source-v1")}
                    ),
                )
            }
        )
    else:
        changes: dict[str, object] = (
            {"table": table("other", "interval-returns-v1")}
            if role == "interval"
            else {"series_id": "benchmark"}
        )
        value = value.model_copy(
            update={
                "evaluation": value.evaluation.model_copy(
                    update={"risk_free": value.evaluation.risk_free.model_copy(update=changes)}
                )
            }
        )
    with pytest.raises(ValidationError):
        value.canonical_bytes()


@pytest.mark.parametrize("role", ["inputs", "datasets", "metrics"])
def test_duplicate_inventories_cannot_be_serialized(role: str) -> None:
    """Duplicate bindings, dataset versions and requested metrics remain invalid on reload."""
    value = strategy()
    if role == "inputs":
        value = value.model_copy(update={"signal_inputs": value.signal_inputs * 2})
    elif role == "datasets":
        value = value.model_copy(update={"datasets": value.datasets * 2})
    else:
        value = value.model_copy(
            update={
                "evaluation": value.evaluation.model_copy(update={"metrics": ("net_mean",) * 2})
            }
        )
    with pytest.raises(ValidationError):
        value.canonical_bytes()


@pytest.mark.parametrize(
    "size,media", [(0, "application/json"), (8388609, "application/json"), (1, "text/plain")]
)
def test_market_source_bounds_precede_admission_reads(size: int, media: str) -> None:
    """Declared raw sources must be nonempty bounded JSON before any store access is possible."""
    value = strategy().market
    artifact = value.table.artifact.model_copy(update={"size_bytes": size, "media_type": media})
    with pytest.raises(ValidationError):
        value.model_copy(
            update={"table": value.table.model_copy(update={"artifact": artifact})}
        ).canonical_bytes()


@pytest.mark.parametrize("role", ["calendar", "manifest"])
def test_calendar_and_manifest_have_their_own_byte_caps(role: str) -> None:
    """Calendar and manifest declarations are bounded independently of the unique closure cap."""
    value = strategy()
    if role == "calendar":
        value = value.model_copy(
            update={
                "timing": value.timing.model_copy(
                    update={"calendar": ref(b"calendar").model_copy(update={"size_bytes": 8388609})}
                )
            }
        )
    else:
        link = value.datasets[0]
        value = value.model_copy(
            update={
                "datasets": (
                    link.model_copy(
                        update={"manifest": link.manifest.model_copy(update={"size_bytes": 262145})}
                    ),
                )
            }
        )
    with pytest.raises(ValidationError):
        value.canonical_bytes()


def test_unique_closure_cap_is_checked() -> None:
    """All unique source evidence counts toward the bounded admission byte inventory."""
    value = strategy()
    with pytest.raises(ValidationError):
        value.model_copy(
            update={"source_refs": (ref(b"large").model_copy(update={"size_bytes": 67108864}),)}
        ).canonical_bytes()


def test_manifest_json_media_is_explicit() -> None:
    """A content hash alone does not supply the manifest's required JSON interpretation."""
    value = strategy()
    link = value.datasets[0]
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "datasets": (
                    link.model_copy(
                        update={
                            "manifest": link.manifest.model_copy(
                                update={"media_type": "text/plain"}
                            )
                        }
                    ),
                )
            }
        ).canonical_bytes()


def test_repeated_hash_metadata_must_agree() -> None:
    """The same content identity cannot acquire a different claimed size in another role."""
    value = strategy()
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "source_refs": (value.market.table.artifact.model_copy(update={"size_bytes": 1}),)
            }
        ).canonical_bytes()


@pytest.mark.parametrize(
    "method", ["execution_sha256", "table_references", "unique_artifacts", "required_coverage"]
)
def test_identity_and_projection_boundaries_revalidate_copied_models(method: str) -> None:
    """Forged nested policy copies cannot bypass validation through a public identity helper."""
    value = strategy().model_copy(update={"formula": "missing"})
    with pytest.raises(ValidationError):
        result = getattr(value, method)
        if callable(result):
            result()
    with pytest.raises(ValidationError):
        strategy().signal_inputs[0].model_copy(update={"frequency": "annual"}).monthly_binding()


@pytest.mark.parametrize("role", ["lag", "history"])
def test_pre_year_one_coverage_fails_with_validation_error(role: str) -> None:
    """Civil warmup subtraction cannot leak an untyped date overflow from hostile metadata."""
    value = strategy()
    changes: dict[str, object] = {
        "evaluation": value.evaluation.model_copy(update={"sample_start": date(1, 1, 1)})
    }
    if role == "lag":
        changes["timing"] = value.timing.model_copy(update={"formation_lag_months": 1})
    else:
        changes["signal_inputs"] = (
            value.signal_inputs[0].model_copy(update={"history_observations": 2}),
        )
    with pytest.raises(ValidationError):
        value.model_copy(update=changes).canonical_bytes()


@pytest.mark.parametrize("role", ["costs", "weighting", "bucket_size", "actions", "cash_carry"])
def test_unsupported_economics_cannot_be_admitted_as_declarations(role: str) -> None:
    """Slope, allocation and carry assumptions are explicit limits of this versioned profile."""
    value = strategy()
    if role in {"costs", "cash_carry"}:
        value = value.model_copy(
            update={
                "costs": value.costs.model_copy(
                    update={"commission_bps": 5000}
                    if role == "costs"
                    else {"annual_interest_bps": 1}
                )
            }
        )
    elif role == "actions":
        value = value.model_copy(
            update={"policies": value.policies.model_copy(update={"corporate_actions": "apply"})}
        )
    else:
        allocation = value.portfolio.allocation.model_copy(
            update={"weighting": "value_weight", "weight_input": "signal"}
            if role == "weighting"
            else {"minimum_bucket_size": 3}
        )
        value = value.model_copy(
            update={"portfolio": value.portfolio.model_copy(update={"allocation": allocation})}
        )
    with pytest.raises(ValidationError):
        value.canonical_bytes()
