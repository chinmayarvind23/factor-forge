"""Retained execution paths supply HAC inputs through verified calendar and result bytes."""

from decimal import Decimal

import pytest
from test_monthly_admission import AT, original_strategy

from factorforge.backtests.monthly import run_monthly
from factorforge.domain.errors import ResearchError
from factorforge.validation.monthly import MonthlyHACRequest, validate_monthly_hac


@pytest.mark.parametrize(
    "cash,lags,reason",
    [
        ("1002", 1, None),
        ("1000", 1, "EXPERIMENT_NOT_COMPLETED"),
        ("1002", 3, "INSUFFICIENT_HAC_SAMPLE"),
    ],
)
def test_saved_monthly_result_has_explicit_diagnostic_outcome(
    cash: str, lags: int, reason: str | None
) -> None:
    """Only complete retained samples with sufficient observations enter the estimator."""
    spec, store = original_strategy()
    run = run_monthly(spec, store, initial_cash_usd=Decimal(cash), evaluated_at=AT)
    ref = store.put(run.canonical_bytes(), media_type="application/json")
    command = MonthlyHACRequest(result=ref, lags=lags, correction="none")
    result = validate_monthly_hac(command, store)
    assert result.reason == reason
    if reason is None:
        assert result.diagnostic is not None and run.performance is not None
        assert result.diagnostic.request.values == tuple(
            row.net_return for row in run.performance.intervals
        )
        assert len(result.diagnostic.request.values) == 3
    else:
        assert result.diagnostic is None
    assert validate_monthly_hac(command, store) == result


@pytest.mark.parametrize("target", ["result", "calendar"])
def test_corrupt_result_or_calendar_bytes_are_rejected(target: str) -> None:
    """Valid reference metadata never substitutes for checking the bytes returned by storage."""
    spec, store = original_strategy()
    run = run_monthly(spec, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)
    ref = store.put(run.canonical_bytes(), media_type="application/json")
    corrupt = ref if target == "result" else spec.timing.calendar
    store.values[corrupt.sha256] = b"{}"
    with pytest.raises(ResearchError):
        validate_monthly_hac(MonthlyHACRequest(result=ref, lags=1, correction="none"), store)


def test_report_return_fields_do_not_override_account_path() -> None:
    """The diagnostic recomputes net returns instead of trusting a saved report's scalar inputs."""
    spec, store = original_strategy()
    run = run_monthly(spec, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)
    assert run.performance is not None
    altered = run.performance.intervals[0].model_copy(
        update={"net_return": Decimal(9), "excess_return": Decimal(9)}
    )
    report = run.performance.model_copy(
        update={"intervals": (altered, *run.performance.intervals[1:])}
    )
    wire = run.model_copy(update={"performance": report}).canonical_bytes()
    ref = store.put(wire, media_type="application/json")
    result = validate_monthly_hac(MonthlyHACRequest(result=ref, lags=1, correction="none"), store)
    assert result.diagnostic is not None
    assert result.diagnostic.request.values[0] == run.performance.intervals[0].net_return
