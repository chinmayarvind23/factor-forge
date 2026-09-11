"""Deterministic fifty-digit metrics over declared complete NAV paths, without inference."""

import hashlib
import json
from decimal import Decimal, DecimalException, localcontext
from itertools import pairwise

from pydantic import ValidationError

from factorforge.domain.accounting import accounting_context
from factorforge.domain.errors import ResearchError
from factorforge.domain.performance import (
    ExecutionBatch,
    MetricValue,
    PerformancePath,
    PerformanceReport,
    ReturnInterval,
    RiskFreeObservation,
)


def _available(value: Decimal) -> MetricValue:
    """Construct a finite available metric through its strict result contract."""
    return MetricValue(status="available", value=value, reason=None)


def _unavailable(reason: str) -> MetricValue:
    """Preserve the specific reason a requested quantity cannot be computed."""
    return MetricValue(status="unavailable", value=None, reason=reason)


def _digest(records: tuple[RiskFreeObservation, ...] | tuple[ExecutionBatch, ...]) -> str:
    """Hash the full validated inventory, including explicit empty input, in canonical order."""
    raw = json.dumps(
        [row.model_dump(mode="json") for row in records],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _rates(
    path: PerformancePath, supplied: object
) -> tuple[tuple[RiskFreeObservation, ...] | None, str | None]:
    """Reject missing, duplicate, malformed or reordered rates without changing the NAV sample."""
    if supplied is None:
        return None, "risk_free_not_supplied"
    if not isinstance(supplied, tuple) or len(supplied) > 10000:
        return None, "risk_free_input_invalid"
    try:
        rows = tuple(RiskFreeObservation.model_validate(row) for row in supplied)
    except (ValidationError, ValueError, TypeError, OverflowError):
        return None, "risk_free_input_invalid"
    expected = tuple(zip(path.session_closes, path.session_closes[1:], strict=False))
    if tuple((row.start_at, row.end_at) for row in rows) != expected:
        return None, "risk_free_alignment_invalid"
    return rows, None


def _turnover(path: PerformancePath, supplied: object) -> tuple[MetricValue, str | None]:
    """An optional complete inventory supports batch ratios; NAV changes cannot infer trades."""
    if supplied is None:
        return _unavailable("execution_turnover_inventory_not_supplied"), None
    if not isinstance(supplied, tuple) or len(supplied) > 10000:
        return _unavailable("execution_turnover_inventory_invalid"), None
    try:
        rows = tuple(ExecutionBatch.model_validate(row) for row in supplied)
        if len({row.batch_id for row in rows}) != len(rows) or len(
            {row.executed_at for row in rows}
        ) != len(rows):
            raise ValueError("Duplicate batch identity or simultaneous batch")
        if any(left.executed_at >= right.executed_at for left, right in pairwise(rows)):
            raise ValueError("Execution inventory must be chronological")
        if any(
            not path.baseline_at <= row.executed_at <= path.session_closes[-1]
            or (
                row.executed_at == path.baseline_at
                and row.pre_trade_nav_usd != path.initial_capital_usd
            )
            for row in rows
        ):
            raise ValueError("Batch falls outside the measured path or contradicts baseline NAV")
        value = sum((row.absolute_notional_usd / row.pre_trade_nav_usd for row in rows), Decimal(0))
        return _available(value), _digest(rows)
    except (ValidationError, ValueError, TypeError, OverflowError, DecimalException):
        return _unavailable("execution_turnover_inventory_invalid"), None


def compute_performance(
    path: PerformancePath,
    *,
    annualization: int,
    risk_free: tuple[RiskFreeObservation, ...] | None,
    execution_batches: tuple[ExecutionBatch, ...] | None,
) -> PerformanceReport:
    """Compute complete-path metrics; external flows, unknown NAV and later insolvency fail."""
    try:
        validated = PerformancePath.model_validate(path)
        if type(annualization) is not int or not 1 <= annualization <= 366:
            raise ValueError("Annualization must be an integer from one through 366")
        with localcontext(accounting_context()):
            return _compute(validated, annualization, risk_free, execution_batches)
    except (ValidationError, ValueError, TypeError, OverflowError, DecimalException):
        raise ResearchError(
            "PERFORMANCE_INPUT_INVALID", "Complete metric inputs exceed the supported contract", 422
        ) from None


def _compute(
    path: PerformancePath,
    annualization: int,
    risk_free: tuple[RiskFreeObservation, ...] | None,
    execution_batches: tuple[ExecutionBatch, ...] | None,
) -> PerformanceReport:
    """All arithmetic shares one explicitly isolated context and a bounded observation count."""
    navs = (path.inception.nav_usd, *(row.nav_usd for row in path.closes))
    if any(value is None for value in navs):
        raise ResearchError("PERFORMANCE_NAV_INCOMPLETE", "Every declared NAV must be known", 422)
    known = tuple(value for value in navs if value is not None)
    if any(value <= 0 for value in known[:-1]):
        raise ResearchError(
            "PERFORMANCE_INSOLVENCY_CONTINUATION",
            "No return interval may follow nonpositive NAV",
            422,
        )
    n = len(path.closes)
    rates, rate_reason = _rates(path, risk_free)
    opening = path.initial_capital_usd
    intervals = []
    for index, row in enumerate(path.closes):
        closing = known[index + 1]
        net = closing / opening - 1
        rf = rates[index].cumulative_return if rates is not None else None
        intervals.append(
            ReturnInterval(
                start_at=path.session_closes[index],
                end_at=row.at,
                net_return=net,
                risk_free_return=rf,
                excess_return=net - rf if rf is not None else None,
            )
        )
        opening = closing
    returns = tuple(row.net_return for row in intervals)
    excess = tuple(row.excess_return for row in intervals if row.excess_return is not None)
    mean = _available(sum(returns, Decimal(0)) / n) if n else _unavailable("no_return_periods")
    if not n:
        excess_mean = variance = sharpe = _unavailable("no_return_periods")
    elif rates is None:
        assert rate_reason is not None
        excess_mean = variance = sharpe = _unavailable(rate_reason)
    else:
        average = sum(excess, Decimal(0)) / n
        excess_mean = _available(average)
        if n < 2:
            variance = sharpe = _unavailable("fewer_than_two_periods")
        else:
            var = sum(((value - average) ** 2 for value in excess), Decimal(0)) / (n - 1)
            variance = _available(var)
            sharpe = (
                _available(Decimal(annualization).sqrt() * average / var.sqrt())
                if var
                else _unavailable("zero_excess_variance")
            )
    peak = path.initial_capital_usd
    drawdowns = [Decimal(0)]
    for value in known:
        peak = max(peak, value)
        drawdowns.append(1 - value / peak)
    turnover, execution_hash = _turnover(path, execution_batches)
    return PerformanceReport(
        outcome="insolvent" if known[-1] <= 0 else "solvent",
        terminal_nav_usd=known[-1],
        annualization=annualization,
        n=n,
        path_sha256=path.sha256,
        risk_free_sha256=_digest(rates) if rates is not None else None,
        execution_batches_sha256=execution_hash,
        intervals=tuple(intervals),
        observed_drawdowns=tuple(drawdowns),
        daily_net_mean=mean,
        daily_excess_mean=excess_mean,
        excess_sample_variance=variance,
        net_sharpe=sharpe,
        total_return=_available(known[-1] / path.initial_capital_usd - 1),
        max_drawdown=_available(max(drawdowns)),
        turnover=turnover,
    )
