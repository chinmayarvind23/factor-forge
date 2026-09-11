"""Original metric examples preserve fee timing, missing-data status and observed insolvency."""

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, DefaultContext, Inexact, localcontext
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from factorforge.backtests.performance import compute_performance
from factorforge.domain.errors import ResearchError
from factorforge.domain.performance import (
    ExecutionBatch,
    NavObservation,
    PerformancePath,
    PerformanceReport,
    RiskFreeObservation,
)

BASE = datetime(2024, 1, 4, 20, tzinfo=UTC)


def path(values: tuple[str, ...] = ("99", "90", "99")) -> PerformancePath:
    """One authored entry fee and two full intervals avoid any same-instant daily observation."""
    times = tuple(BASE + timedelta(days=index) for index in range(len(values)))
    return PerformancePath(
        initial_capital_usd=Decimal(100),
        baseline_at=BASE,
        inception=NavObservation(at=BASE, nav_usd=Decimal(values[0])),
        session_closes=times,
        closes=tuple(
            NavObservation(at=at, nav_usd=Decimal(value))
            for at, value in zip(times[1:], values[1:], strict=True)
        ),
        external_cash_flows=False,
    )


def rates(
    value: PerformancePath, returns: tuple[str, ...] = ("0", "0")
) -> tuple[RiskFreeObservation, ...]:
    """Cumulative rate observations bind exact adjacent endpoints, not just civil dates."""
    return tuple(
        RiskFreeObservation(start_at=start, end_at=end, cumulative_return=Decimal(rate))
        for start, end, rate in zip(
            value.session_closes[:-1], value.session_closes[1:], returns, strict=True
        )
    )


def test_entry_fee_is_in_first_full_period_and_drawdown_baseline() -> None:
    """The fee is not lost to a post-cost denominator or assigned a zero-length sampling weight."""
    value = path()
    result = compute_performance(
        value, annualization=252, risk_free=rates(value), execution_batches=()
    )
    assert result.n == 2
    assert [period.net_return for period in result.intervals] == [Decimal("-0.1"), Decimal("0.1")]
    assert result.total_return.value == Decimal("-0.01")
    assert result.daily_net_mean.value == 0
    assert result.excess_sample_variance.value == Decimal("0.02")
    assert result.net_sharpe.value == 0
    assert result.max_drawdown.value == Decimal("0.1")
    assert result.observed_drawdowns == (
        Decimal(0),
        Decimal("0.01"),
        Decimal("0.1"),
        Decimal("0.01"),
    )
    assert result.turnover.value == 0


def test_varying_rf_changes_excess_variance_without_changing_net_metrics() -> None:
    """Both parts of the Sharpe ratio use the differential-return series."""
    value = path()
    result = compute_performance(
        value, annualization=1, risk_free=rates(value, ("0", "0.1")), execution_batches=None
    )
    assert result.daily_net_mean.value == 0
    assert result.daily_excess_mean.value == Decimal("-0.05")
    assert result.excess_sample_variance.value == Decimal("0.005")
    assert result.net_sharpe.value is not None and result.net_sharpe.value < 0
    assert result.turnover.status == "unavailable"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "endpoint", "absent"])
def test_bad_rf_preserves_valid_net_metrics(mutation: str) -> None:
    """Risk-free failures disable only dependent metrics and never shorten the net sample."""
    value = path()
    rf: tuple[RiskFreeObservation, ...] | None = rates(value)
    assert rf is not None
    if mutation == "missing":
        rf = rf[:1]
    elif mutation == "duplicate":
        rf = (rf[0], rf[0])
    elif mutation == "endpoint":
        rf = (rf[0], rf[1].model_copy(update={"end_at": BASE + timedelta(hours=47)}))
    else:
        rf = None
    result = compute_performance(value, annualization=252, risk_free=rf, execution_batches=None)
    assert result.n == 2 and result.daily_net_mean.value == 0
    assert result.total_return.value == Decimal("-0.01")
    assert result.max_drawdown.value == Decimal("0.1")
    assert all(
        metric.status == "unavailable"
        for metric in (result.daily_excess_mean, result.excess_sample_variance, result.net_sharpe)
    )


@pytest.mark.parametrize("terminal", ["0", "-10"])
def test_terminal_insolvency_is_preserved_but_cannot_continue(terminal: str) -> None:
    """Known zero and negative terminal wealth are losses, not missing observations."""
    value = path(("100", terminal))
    result = compute_performance(
        value, annualization=252, risk_free=rates(value, ("0",)), execution_batches=None
    )
    assert result.total_return.value == Decimal(terminal) / 100 - 1
    assert result.max_drawdown.value == 1 - Decimal(terminal) / 100
    assert result.net_sharpe.reason == "fewer_than_two_periods"
    with pytest.raises(ResearchError):
        compute_performance(
            path(("100", terminal, "100")),
            annualization=252,
            risk_free=None,
            execution_batches=None,
        )


def test_inception_insolvency_has_no_daily_sample() -> None:
    """An immediate loss remains in total return and drawdown even with zero later periods."""
    result = compute_performance(
        path(("-10",)), annualization=252, risk_free=(), execution_batches=None
    )
    assert result.n == 0 and result.total_return.value == Decimal("-1.1")
    assert result.max_drawdown.value == Decimal("1.1")
    assert result.daily_net_mean.reason == "no_return_periods"
    assert result.net_sharpe.reason == "no_return_periods"


def test_turnover_uses_each_batchs_pre_trade_nav_and_known_zero_is_distinct() -> None:
    """An entry plus smaller later liquidation sums two batch ratios rather than two notionals."""
    value = path(("100", "90", "90"))
    batches = (
        ExecutionBatch(
            batch_id="entry",
            executed_at=BASE,
            absolute_notional_usd=Decimal(100),
            pre_trade_nav_usd=Decimal(100),
        ),
        ExecutionBatch(
            batch_id="exit",
            executed_at=BASE + timedelta(days=1),
            absolute_notional_usd=Decimal(90),
            pre_trade_nav_usd=Decimal(90),
        ),
    )
    result = compute_performance(
        value, annualization=252, risk_free=rates(value), execution_batches=batches
    )
    assert result.turnover.value == 2


def test_missing_declared_close_and_unknown_nav_fail_typed() -> None:
    """An incomplete path cannot become a successful shorter sample or an imputed zero loss."""
    value = path()
    bad = (
        value.model_copy(update={"closes": value.closes[:1]}),
        value.model_copy(
            update={
                "closes": (value.closes[0], value.closes[1].model_copy(update={"nav_usd": None}))
            }
        ),
    )
    for candidate in bad:
        with pytest.raises(ResearchError):
            compute_performance(
                candidate, annualization=252, risk_free=None, execution_batches=None
            )


@pytest.mark.parametrize("token", ["1", "1.00000000000000000001", "1e-20"])
def test_json_numeric_tokens_are_rejected_before_precision_loss(token: str) -> None:
    """The wire requires exact decimal strings, even for integer-looking amounts."""
    raw = '{"at":"2024-01-04T20:00:00Z","nav_usd":' + token + "}"
    with pytest.raises(ValidationError):
        NavObservation.model_validate_json(raw)
    parsed = NavObservation.model_validate_json(raw.replace(token + "}", '"' + token + '"}'))
    assert parsed.nav_usd == Decimal(token)


@pytest.mark.parametrize("amount", ["1e-101", "1e101", "NaN", "Infinity", "1." + "2" * 50])
def test_input_precision_and_exponents_are_bounded(amount: str) -> None:
    """Unsupported precision fails explicitly instead of rounding accepted input."""
    with pytest.raises(ValidationError):
        NavObservation(at=BASE, nav_usd=Decimal(amount))


def test_decimal_wire_and_saved_report_round_trip() -> None:
    """Money and rate strings retain fine digits through serialization and replay."""
    fine = Decimal("1.00000000000000000001")
    rf = RiskFreeObservation(start_at=BASE, end_at=BASE + timedelta(days=1), cumulative_return=fine)
    assert RiskFreeObservation.model_validate_json(rf.model_dump_json()) == rf
    raw = json.loads(rf.model_dump_json())
    raw["cumulative_return"] = 1.0
    with pytest.raises(ValidationError):
        RiskFreeObservation.model_validate_json(json.dumps(raw))
    result = compute_performance(
        path(), annualization=252, risk_free=rates(path()), execution_batches=()
    )
    assert PerformanceReport.model_validate_json(result.model_dump_json()) == result
    raw = json.loads(result.model_dump_json())
    raw["total_return"]["value"] = -0.01
    with pytest.raises(ValidationError):
        PerformanceReport.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("annualization", [0, 367, True, 252.0, "252"])
def test_annualization_is_explicit_bounded_integer(annualization: object) -> None:
    """Scaling cannot inherit defaults or coerce booleans or numeric strings."""
    with pytest.raises(ResearchError):
        compute_performance(
            path(), annualization=cast(int, annualization), risk_free=None, execution_batches=None
        )


@pytest.mark.parametrize("kind", ["nan", "numeric", "backward", "list", "oversize"])
def test_malformed_rf_is_metric_specific_unavailable(kind: str) -> None:
    """Forged or wrong-container RF leaves valid net evidence available."""
    value = path()
    rows: object = rates(value)
    if kind == "nan":
        rows = (rates(value)[0].model_copy(update={"cumulative_return": Decimal("NaN")}),)
    elif kind == "numeric":
        rows = (rates(value)[0].model_copy(update={"cumulative_return": 0.0}),)
    elif kind == "backward":
        rows = (rates(value)[0].model_copy(update={"end_at": BASE}),)
    elif kind == "list":
        rows = list(rates(value))
    else:
        rows = (rates(value)[0],) * 10001
    result = compute_performance(
        value,
        annualization=252,
        risk_free=cast(tuple[RiskFreeObservation, ...], rows),
        execution_batches=None,
    )
    assert result.daily_excess_mean.reason == "risk_free_input_invalid"
    assert result.daily_net_mean.status == "available" and result.n == 2


@pytest.mark.parametrize(
    "kind", ["duplicate_id", "same_time", "outside", "baseline_nav", "negative", "list", "oversize"]
)
def test_bad_execution_inventory_disables_only_turnover(kind: str) -> None:
    """Bad inventory cannot masquerade as zero or partial turnover."""
    batch = ExecutionBatch(
        batch_id="entry",
        executed_at=BASE,
        absolute_notional_usd=Decimal(100),
        pre_trade_nav_usd=Decimal(100),
    )
    rows: object
    if kind == "duplicate_id":
        rows = (batch, batch.model_copy(update={"executed_at": BASE + timedelta(hours=1)}))
    elif kind == "same_time":
        rows = (batch, batch.model_copy(update={"batch_id": "another"}))
    elif kind == "outside":
        rows = (batch.model_copy(update={"executed_at": BASE - timedelta(seconds=1)}),)
    elif kind == "baseline_nav":
        rows = (batch.model_copy(update={"pre_trade_nav_usd": Decimal(99)}),)
    elif kind == "negative":
        rows = (batch.model_copy(update={"absolute_notional_usd": Decimal(-1)}),)
    elif kind == "list":
        rows = [batch]
    else:
        rows = (batch,) * 10001
    result = compute_performance(
        path(),
        annualization=252,
        risk_free=rates(path()),
        execution_batches=cast(tuple[ExecutionBatch, ...], rows),
    )
    assert result.turnover.reason == "execution_turnover_inventory_invalid"
    assert result.turnover.value is None and result.daily_net_mean.value == 0


@pytest.mark.parametrize("kind", ["external", "duplicate", "unordered", "inception", "initial"])
def test_copied_path_cannot_bypass_complete_sample_contract(kind: str) -> None:
    """Copying immutable models cannot bypass public arithmetic validation."""
    value = path()
    update: dict[str, object] = {"external_cash_flows": True}
    if kind == "duplicate":
        update = {"session_closes": (BASE, BASE, BASE)}
    elif kind == "unordered":
        update = {"session_closes": tuple(reversed(value.session_closes))}
    elif kind == "inception":
        update = {
            "inception": value.inception.model_copy(update={"at": BASE + timedelta(seconds=1)})
        }
    elif kind == "initial":
        update = {"initial_capital_usd": Decimal(0)}
    with pytest.raises(ResearchError):
        compute_performance(
            value.model_copy(update=update),
            annualization=252,
            risk_free=None,
            execution_batches=None,
        )


def test_fold_clocks_normalize_before_ordering_and_hashing() -> None:
    """The repeated civil hour still describes one forward UTC interval."""
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=0)
    end = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=1)
    value = PerformancePath(
        initial_capital_usd=Decimal(100),
        baseline_at=start,
        inception=NavObservation(at=start, nav_usd=Decimal(100)),
        session_closes=(start, end),
        closes=(NavObservation(at=end, nav_usd=Decimal(110)),),
        external_cash_flows=False,
    )
    result = compute_performance(
        value, annualization=252, risk_free=rates(value, ("0",)), execution_batches=None
    )
    assert result.n == 1 and result.total_return.value == Decimal("0.1")
    assert value.session_closes[1] - value.session_closes[0] == timedelta(hours=1)
    assert PerformancePath.model_validate_json(value.model_dump_json()).sha256 == value.sha256


def test_utc_overflow_is_validation_failure() -> None:
    """UTC conversion cannot escape as platform-dependent datetime overflow."""
    extreme = datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))
    with pytest.raises(ValidationError):
        NavObservation(at=extreme, nav_usd=Decimal(1))
    value = path().model_copy(update={"session_closes": (extreme,)})
    with pytest.raises(ResearchError):
        compute_performance(value, annualization=252, risk_free=None, execution_batches=None)


def test_isolated_decimal_context_ignores_mutable_process_defaults() -> None:
    """Caller context and future Context defaults cannot change a replayed metric."""
    value = path(("99", "93", "107"))
    expected = compute_performance(
        value, annualization=252, risk_free=rates(value), execution_batches=()
    )
    saved = DefaultContext.copy()
    try:
        DefaultContext.prec = 3
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.traps[Inexact] = True
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            actual = compute_performance(
                value, annualization=252, risk_free=rates(value), execution_batches=()
            )
        assert actual == expected
    finally:
        DefaultContext.prec = saved.prec
        DefaultContext.rounding = saved.rounding
        DefaultContext.traps = saved.traps.copy()


def test_zero_excess_variance_is_undefined_sharpe_not_zero() -> None:
    """A cash-only path has zero measured variance and no defined Sharpe ratio."""
    value = path(("100", "100", "100"))
    result = compute_performance(
        value, annualization=366, risk_free=rates(value), execution_batches=None
    )
    assert result.excess_sample_variance.value == 0
    assert result.net_sharpe.reason == "zero_excess_variance"


@pytest.mark.parametrize(
    "kind",
    [
        "count",
        "gap",
        "negative_drawdown",
        "baseline_drawdown",
        "maximum",
        "status",
        "interval",
        "variance",
    ],
)
def test_saved_report_revalidates_nested_coherence(kind: str) -> None:
    """Reloading copied output records cannot bypass retained inventory and status invariants."""
    value = path()
    result = compute_performance(
        value, annualization=252, risk_free=rates(value), execution_batches=()
    )
    update: dict[str, object]
    if kind == "count":
        update = {"n": 1}
    elif kind == "gap":
        update = {
            "intervals": (
                result.intervals[0],
                result.intervals[1].model_copy(update={"start_at": BASE + timedelta(hours=25)}),
            )
        }
    elif kind == "negative_drawdown":
        update = {"observed_drawdowns": (Decimal(0), Decimal(-1), Decimal(0), Decimal(0))}
    elif kind == "baseline_drawdown":
        update = {"observed_drawdowns": (Decimal(1), Decimal(0), Decimal(0), Decimal(0))}
    elif kind == "maximum":
        update = {"max_drawdown": result.max_drawdown.model_copy(update={"value": Decimal(2)})}
    elif kind == "status":
        update = {"total_return": result.total_return.model_copy(update={"reason": "missing"})}
    elif kind == "interval":
        update = {
            "intervals": (
                result.intervals[0].model_copy(update={"excess_return": None}),
                result.intervals[1],
            )
        }
    else:
        update = {
            "excess_sample_variance": result.excess_sample_variance.model_copy(
                update={"value": Decimal(-1)}
            )
        }
    with pytest.raises(ValidationError):
        result.model_copy(update=update).canonical_bytes()


def test_inception_and_positive_denominator_endpoints() -> None:
    """A tiny supported positive balance still reports a finite large observed loss."""
    tiny = Decimal("1e-100")
    value = PerformancePath(
        initial_capital_usd=tiny,
        baseline_at=BASE,
        inception=NavObservation(at=BASE, nav_usd=tiny),
        session_closes=(BASE, BASE + timedelta(days=1)),
        closes=(NavObservation(at=BASE + timedelta(days=1), nav_usd=Decimal("-1e24")),),
        external_cash_flows=False,
    )
    result = compute_performance(
        value, annualization=1, risk_free=rates(value, ("0",)), execution_batches=()
    )
    assert result.total_return.value is not None and result.total_return.value < -1
    assert result.max_drawdown.value is not None and result.max_drawdown.value > 1
    with pytest.raises(ResearchError):
        compute_performance(
            path(("-10", "100")), annualization=252, risk_free=None, execution_batches=None
        )


def test_cash_rf_cannot_lose_more_than_its_entire_starting_value() -> None:
    """A forged rate below minus one disables RF metrics while a known full loss is valid."""
    value = path()
    rows = rates(value)
    invalid = (rows[0].model_copy(update={"cumulative_return": Decimal("-1.01")}), rows[1])
    result = compute_performance(
        value, annualization=252, risk_free=invalid, execution_batches=None
    )
    assert result.daily_excess_mean.reason == "risk_free_input_invalid"
    assert result.daily_net_mean.value == 0
    complete_loss = compute_performance(
        value, annualization=252, risk_free=rates(value, ("-1", "0")), execution_batches=None
    )
    assert complete_loss.daily_excess_mean.status == "available"


@pytest.mark.parametrize(
    "values,outcome",
    [
        (("100", "0"), "insolvent"),
        (("100", "-10"), "insolvent"),
        (("-10",), "insolvent"),
        (("100", "90"), "solvent"),
    ],
)
def test_outcome_explicitly_records_terminal_insolvency(
    values: tuple[str, ...], outcome: str
) -> None:
    """A complete known insolvent result remains distinguishable from missing evidence."""
    result = compute_performance(
        path(values), annualization=252, risk_free=None, execution_batches=None
    )
    assert result.model_dump()["outcome"] == outcome
    wrong = "solvent" if outcome == "insolvent" else "insolvent"
    with pytest.raises(ValidationError):
        result.model_copy(update={"outcome": wrong}).canonical_bytes()


def test_execution_batches_must_have_declared_chronological_order() -> None:
    """Chronological input prevents summation order from becoming an undeclared choice."""
    entry = ExecutionBatch(
        batch_id="entry",
        executed_at=BASE,
        absolute_notional_usd=Decimal(100),
        pre_trade_nav_usd=Decimal(100),
    )
    later = ExecutionBatch(
        batch_id="later",
        executed_at=BASE + timedelta(hours=1),
        absolute_notional_usd=Decimal(10),
        pre_trade_nav_usd=Decimal(99),
    )
    result = compute_performance(
        path(), annualization=252, risk_free=None, execution_batches=(later, entry)
    )
    assert result.turnover.reason == "execution_turnover_inventory_invalid"


def test_tiny_positive_terminal_nav_is_not_rounded_into_insolvency() -> None:
    """Exact retained NAV determines insolvency when fifty-digit loss rounds to minus one."""
    result = compute_performance(
        path(("100", "1e-100")), annualization=252, risk_free=None, execution_batches=None
    )
    assert result.terminal_nav_usd == Decimal("1e-100")
    assert result.total_return.value == -1 and result.outcome == "solvent"


@pytest.mark.parametrize(
    "kind", ["excess", "rf_identity", "net_mean", "excess_mean", "rounded_outcome"]
)
def test_saved_report_rates_and_mean_statuses_are_coherent(kind: str) -> None:
    """Receipt structure cannot contradict retained rates, sample count or terminal loss."""
    value = path()
    result = compute_performance(
        value, annualization=252, risk_free=rates(value), execution_batches=()
    )
    update: dict[str, object]
    if kind == "excess":
        update = {
            "intervals": (
                result.intervals[0].model_copy(update={"excess_return": Decimal(5)}),
                result.intervals[1],
            )
        }
    elif kind == "rf_identity":
        update = {"risk_free_sha256": None}
    elif kind == "net_mean":
        update = {
            "daily_net_mean": result.daily_net_mean.model_copy(
                update={"status": "unavailable", "value": None, "reason": "no_return_periods"}
            )
        }
    elif kind == "excess_mean":
        update = {
            "daily_excess_mean": result.daily_excess_mean.model_copy(
                update={"status": "unavailable", "value": None, "reason": "risk_free_not_supplied"}
            )
        }
    else:
        update = {"total_return": result.total_return.model_copy(update={"value": Decimal(-2)})}
    with pytest.raises(ValidationError):
        result.model_copy(update=update).canonical_bytes()
