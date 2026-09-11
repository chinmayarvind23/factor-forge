"""Bartlett Newey-West covariance of an intercept-only mean with explicit finite-sample policy."""

from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.domain.accounting import accounting_context
from factorforge.domain.factors import Contract
from factorforge.domain.performance import Amount, MetricValue, Number


class HACRequest(Contract):
    """Ordered, equally spaced observations are supplied by a validated series/fold adapter."""

    schema_version: Literal["hac-mean-request-v1"] = "hac-mean-request-v1"
    values: Annotated[tuple[Amount, ...], Field(min_length=2, max_length=10000)]
    lags: Annotated[int, Field(ge=0, le=120)]
    correction: Literal["none", "n_over_n_minus_one"]

    @model_validator(mode="after")
    def supported_lags(self) -> Self:
        """An explicit lag window must fit within the retained sample."""
        if self.lags >= len(self.values):
            raise ValueError("HAC lag window must be smaller than the sample")
        return self


class HACResult(Contract):
    """Retain the complete series and choices without inferring a p-value or promotion decision."""

    schema_version: Literal["hac-mean-result-v1"] = "hac-mean-result-v1"
    method: Literal["bartlett-intercept-exact-fraction-decimal50-v1"] = (
        "bartlett-intercept-exact-fraction-decimal50-v1"
    )
    request: HACRequest
    mean: Number
    variance_mean: Number
    standard_error: Number
    t_statistic: MetricValue


def _decimal(value: Fraction) -> Decimal:
    """Convert only at the output boundary inside the caller's fixed fifty-digit context."""
    return Decimal(value.numerator) / Decimal(value.denominator)


def hac_mean(request: HACRequest) -> HACResult:
    """Estimate mean covariance using Bartlett weights and exact residual cross-products.

    S = sum(u_t^2) + 2 sum_l (1-l/(L+1)) sum_t u_t u_(t-l).
    The mean's covariance is S/n^2, optionally multiplied by n/(n-1).
    Equal spacing is a caller obligation; missing observations must not be compressed away.
    """
    request = HACRequest.model_validate(request)
    values = tuple(Fraction(value) for value in request.values)
    n = len(values)
    mean = sum(values, Fraction()) / n
    residuals = tuple(value - mean for value in values)
    total = sum((value * value for value in residuals), Fraction())
    for lag in range(1, request.lags + 1):
        cross = sum((residuals[i] * residuals[i - lag] for i in range(lag, n)), Fraction())
        total += 2 * Fraction(request.lags + 1 - lag, request.lags + 1) * cross
    variance = total / (n * n)
    if request.correction == "n_over_n_minus_one":
        variance *= Fraction(n, n - 1)
    if variance < 0:
        raise ValueError("Exact Bartlett covariance cannot be negative")
    with localcontext(accounting_context()):
        mean_decimal, variance_decimal = _decimal(mean), _decimal(variance)
        standard_error = variance_decimal.sqrt()
        statistic = (
            MetricValue(status="available", value=mean_decimal / standard_error, reason=None)
            if variance > 0
            else MetricValue(status="unavailable", value=None, reason="ZERO_HAC_VARIANCE")
        )
        return HACResult(
            request=request,
            mean=mean_decimal,
            variance_mean=variance_decimal,
            standard_error=standard_error,
            t_statistic=statistic,
        )
