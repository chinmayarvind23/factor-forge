"""Original exact examples verify Bartlett lag weights and mean-estimator scaling."""

import json
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from factorforge.validation.hac import HACRequest, hac_mean


def request() -> HACRequest:
    """Four original observations have exact lag-one variance of the mean 25/64."""
    return HACRequest(values=tuple(map(Decimal, (1, 2, 3, 4))), lags=1, correction="none")


def test_independent_exact_lag_one_reference() -> None:
    """The hand sum of squared residuals is 5 and adjacent products sum to 1.25."""
    result = hac_mean(request())
    assert result.mean == Decimal("2.5")
    assert result.variance_mean == Decimal("0.390625")
    assert result.standard_error == Decimal("0.625")
    assert result.t_statistic.value == Decimal(4)


def test_small_sample_correction_is_explicit() -> None:
    """Intercept-only correction multiplies covariance by n/(n-1), not its square root."""
    result = hac_mean(request().model_copy(update={"correction": "n_over_n_minus_one"}))
    assert float(result.variance_mean) == pytest.approx(25 / 48, rel=1e-14)


def test_constant_series_retains_zero_variance_and_undefined_t() -> None:
    """Constant nonzero returns cannot acquire an infinite significance score."""
    result = hac_mean(request().model_copy(update={"values": (Decimal(2),) * 4}))
    assert result.variance_mean == result.standard_error == 0
    assert result.t_statistic.status == "unavailable"
    assert result.t_statistic.reason == "ZERO_HAC_VARIANCE"


def test_ambient_decimal_precision_cannot_change_result() -> None:
    """Computation and serialization use the declared arithmetic context."""
    baseline = hac_mean(request())
    with localcontext() as context:
        context.prec = 3
        assert hac_mean(request()) == baseline


def test_frozen_statsmodels_intercept_references() -> None:
    """Independent OLS sandwich outputs cover several lag windows and both correction choices."""
    fixture = Path(__file__).parents[2] / "data/validation/hac-reference.json"
    reference = json.loads(fixture.read_text(encoding="utf-8"))
    assert reference["statsmodels"] == "0.14.6" and len(reference["cases"]) == 14
    for case in reference["cases"]:
        result = hac_mean(
            HACRequest.model_validate_json(
                json.dumps(
                    {
                        "values": case["values"],
                        "lags": case["lags"],
                        "correction": case["correction"],
                    }
                )
            )
        )
        for field in ("mean", "variance_mean", "standard_error"):
            assert float(getattr(result, field)) == pytest.approx(case[field], rel=1e-12, abs=1e-15)
        assert result.t_statistic.value is not None
        assert float(result.t_statistic.value) == pytest.approx(
            case["t_statistic"], rel=1e-12, abs=1e-15
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"lags": True},
        {"lags": -1},
        {"lags": 4},
        {"values": (Decimal(1),)},
        {"values": (Decimal("NaN"), Decimal(2))},
    ],
)
def test_invalid_samples_and_lags_are_rejected(changes: dict[str, object]) -> None:
    """Copied models do not bypass finite input, sample size or lag-window bounds."""
    with pytest.raises(ValidationError):
        hac_mean(request().model_copy(update=changes))
