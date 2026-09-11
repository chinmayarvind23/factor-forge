"""Bounded conditional NAV metrics preserve observed losses and explicit missing inputs."""

from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field, model_validator

from factorforge.domain.accounting import accounting_context, accounting_utc, exact_decimal_wire
from factorforge.domain.factors import Contract, Digest, Identifier


def bounded_number(value: Decimal) -> Decimal:
    """Bound coefficients and exponents before arithmetic while preserving all input digits."""
    parts = value.as_tuple()
    if (
        not value.is_finite()
        or len(parts.digits) > 50
        or not isinstance(parts.exponent, int)
        or abs(parts.exponent) > 400
    ):
        raise ValueError("Metric numbers exceed supported finite precision")
    return value


Number = Annotated[
    Decimal,
    Field(allow_inf_nan=False, ge=Decimal("-1e300"), le=Decimal("1e300")),
    BeforeValidator(exact_decimal_wire, json_schema_input_type=str),
    AfterValidator(bounded_number),
]


def bounded_input(value: Decimal) -> Decimal:
    """Input exponent bounds keep return ratios and squared deviations representable."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or not -100 <= exponent <= 100:
        raise ValueError("Metric input exponent exceeds supported bounds")
    return value


Amount = Annotated[
    Number, Field(ge=Decimal("-1e24"), le=Decimal("1e24")), AfterValidator(bounded_input)
]
Positive = Annotated[Amount, Field(ge=Decimal("1e-100"))]
Instant = Annotated[AwareDatetime, AfterValidator(accounting_utc)]


class NavObservation(Contract):
    """Null means unknown NAV, never a zero balance; complete computation rejects it."""

    at: Instant
    nav_usd: Amount | None


class PerformancePath(Contract):
    """An authored close inventory includes the pre-trade baseline and every later session."""

    initial_capital_usd: Positive
    baseline_at: Instant
    inception: NavObservation
    session_closes: Annotated[tuple[Instant, ...], Field(min_length=1, max_length=10001)]
    closes: Annotated[tuple[NavObservation, ...], Field(max_length=10000)]
    external_cash_flows: bool

    @model_validator(mode="after")
    def complete_inventory(self) -> Self:
        """Exact ordered timestamps prohibit shortened samples and zero-length daily periods."""
        if self.external_cash_flows:
            raise ValueError("External cash flows are unsupported")
        if self.inception.at != self.baseline_at or self.session_closes[0] != self.baseline_at:
            raise ValueError("Inception and first declared session must match the baseline")
        if any(
            left >= right
            for left, right in zip(self.session_closes, self.session_closes[1:], strict=False)
        ):
            raise ValueError("Declared closes must be strictly increasing")
        if tuple(row.at for row in self.closes) != self.session_closes[1:]:
            raise ValueError("Every declared later session requires exactly one NAV")
        return self


class RiskFreeObservation(Contract):
    """Rates are cumulative returns for exact intervals, without an annual-yield conversion."""

    start_at: Instant
    end_at: Instant
    cumulative_return: Annotated[Amount, Field(ge=Decimal(-1))]

    @model_validator(mode="after")
    def forward_interval(self) -> Self:
        """A rate cannot describe a backward or instantaneous holding interval."""
        if self.start_at >= self.end_at:
            raise ValueError("Risk-free interval must be forward")
        return self


class ExecutionBatch(Contract):
    """One simultaneous authored batch supplies aggregate absolute notional and pre-fee NAV."""

    batch_id: Identifier
    executed_at: Instant
    absolute_notional_usd: Annotated[Amount, Field(ge=0)]
    pre_trade_nav_usd: Positive


class MetricValue(Contract):
    """Unavailable results carry a reason instead of silently becoming zero."""

    status: Literal["available", "unavailable"]
    value: Number | None
    reason: Identifier | None

    @model_validator(mode="after")
    def coherent_status(self) -> Self:
        """A metric has either one finite value or one explicit absence reason."""
        if (self.status == "available" and (self.value is None or self.reason is not None)) or (
            self.status == "unavailable" and (self.value is not None or self.reason is None)
        ):
            raise ValueError("Metric status does not match its value and reason")
        return self


class ReturnInterval(Contract):
    """The retained interval series makes the sample denominator and RF alignment reviewable."""

    start_at: Instant
    end_at: Instant
    net_return: Number
    risk_free_return: Annotated[Number, Field(ge=Decimal(-1))] | None
    excess_return: Number | None

    @model_validator(mode="after")
    def coherent_interval(self) -> Self:
        """A forward net interval has either both differential-return inputs or neither."""
        if self.start_at >= self.end_at or (self.risk_free_return is None) != (
            self.excess_return is None
        ):
            raise ValueError("Return interval is inconsistent")
        if self.risk_free_return is not None:
            with localcontext(accounting_context()):
                if self.excess_return != self.net_return - self.risk_free_return:
                    raise ValueError("Excess return must equal net return minus the aligned rate")
        return self


class PerformanceReport(Contract):
    """Conditional arithmetic is not a research benchmark or an execution-admission verdict."""

    scope: Literal["conditional-complete-nav-metrics"] = "conditional-complete-nav-metrics"
    arithmetic: Literal["decimal-50-half-even-v1"] = "decimal-50-half-even-v1"
    outcome: Literal["solvent", "insolvent"]
    terminal_nav_usd: Amount
    annualization: Annotated[int, Field(ge=1, le=366)]
    n: Annotated[int, Field(ge=0, le=10000)]
    path_sha256: Digest
    risk_free_sha256: Digest | None
    execution_batches_sha256: Digest | None
    intervals: Annotated[tuple[ReturnInterval, ...], Field(max_length=10000)]
    observed_drawdowns: Annotated[tuple[Number, ...], Field(min_length=2, max_length=10002)]
    daily_net_mean: MetricValue
    daily_excess_mean: MetricValue
    excess_sample_variance: MetricValue
    net_sharpe: MetricValue
    total_return: MetricValue
    max_drawdown: MetricValue
    turnover: MetricValue

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        """Reloaded reports retain complete samples, chronological intervals and observed peaks."""
        if self.n != len(self.intervals) or len(self.observed_drawdowns) != self.n + 2:
            raise ValueError("Metric sample counts do not match retained observations")
        if any(
            left.end_at != right.start_at
            for left, right in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("Metric intervals are not contiguous")
        if self.observed_drawdowns[0] != 0 or any(value < 0 for value in self.observed_drawdowns):
            raise ValueError("Observed drawdowns require a zero baseline and nonnegative losses")
        if (
            self.max_drawdown.value != max(self.observed_drawdowns)
            or self.total_return.value is None
        ):
            raise ValueError("Total return and observed maximum drawdown must be available")
        if (self.outcome == "insolvent") != (self.terminal_nav_usd <= 0):
            raise ValueError("The outcome must agree with the exact terminal NAV sign")
        if (self.outcome == "insolvent" and self.total_return.value > -1) or (
            self.outcome == "solvent" and self.total_return.value < -1
        ):
            raise ValueError("The outcome contradicts the rounded total return")
        if self.n and any(
            (row.risk_free_return is not None) != (self.risk_free_sha256 is not None)
            for row in self.intervals
        ):
            raise ValueError("Risk-free identity must agree with every retained interval")
        if (self.daily_net_mean.status == "available") != (self.n > 0):
            raise ValueError("Net mean availability must agree with the sample count")
        if (self.daily_excess_mean.status == "available") != (
            self.n > 0 and self.risk_free_sha256 is not None
        ):
            raise ValueError(
                "Excess mean availability must agree with aligned rates and sample count"
            )
        for metric in (self.excess_sample_variance, self.turnover):
            if metric.value is not None and metric.value < 0:
                raise ValueError("Variance and turnover cannot be negative")
        return self
