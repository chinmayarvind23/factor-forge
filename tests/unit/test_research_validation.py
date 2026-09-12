"""Real retained execution evidence feeds time-aware fold diagnostics without redispatch."""

from datetime import timedelta
from decimal import Decimal

import pytest
from test_monthly_admission import AT, original_strategy

from factorforge.backtests.monthly import run_monthly
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.performance import ReturnInterval
from factorforge.lineage.closure import verify_closure
from factorforge.validation.research import ValidationRequest, assess_folds, validate_research


@pytest.mark.parametrize("cash", ["1002", "1000"])
def test_retained_execution_folds_and_replay(cash: str) -> None:
    """A complete three-return fixture has one test interval; no invented HAC estimate appears."""
    spec, store = original_strategy()
    run = run_monthly(spec, store, initial_cash_usd=Decimal(cash), evaluated_at=AT)
    root = store.put(run.canonical_bytes(), media_type="application/json")
    request = ValidationRequest(
        result=root, initial_train_size=2, test_size=2, hac_lags=0, embargo_seconds=0
    )
    result = validate_research(request, store)
    if cash == "1002":
        assert len(result.folds) == 1
        fold = result.folds[0]
        assert fold.walk_forward.train == (0,)
        assert fold.walk_forward.purged == (1,)
        assert fold.walk_forward.test == (2,)
        assert fold.test_diagnostic is None
        assert fold.reason == "INSUFFICIENT_HAC_SAMPLE"
        assert result.full_sample.diagnostic is not None
    else:
        assert result.reason == "EXPERIMENT_NOT_COMPLETED"
        assert result.folds == ()
    assert validate_research(request, store) == result
    ref = store.put(result.canonical_bytes(), media_type="application/json")
    assert len(verify_closure(ref, store)) > 20


def test_fold_budget_rejected_before_execution() -> None:
    """Configuration cannot request an unbounded number of statistical diagnostics."""
    spec, store = original_strategy()
    run = run_monthly(spec, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)
    root = store.put(run.canonical_bytes(), media_type="application/json")
    result = validate_research(
        ValidationRequest(
            result=root, initial_train_size=3, test_size=1, hac_lags=0, embargo_seconds=0
        ),
        store,
    )
    assert result.reason == "INSUFFICIENT_SPLIT_SAMPLE"
    assert result.folds == ()


def test_longer_contiguous_test_blocks_keep_training_out_of_statistics() -> None:
    """Twelve authored returns yield three test blocks with hand-checkable means and embargo."""
    intervals = tuple(
        ReturnInterval(
            start_at=AT + timedelta(days=i),
            end_at=AT + timedelta(days=i + 1),
            net_return=Decimal(i + 1) / 100,
            risk_free_return=None,
            excess_return=None,
        )
        for i in range(12)
    )
    request = ValidationRequest(
        result=ArtifactRef(sha256="0" * 64, size_bytes=2, media_type="application/json"),
        initial_train_size=3,
        test_size=3,
        hac_lags=0,
        embargo_seconds=86400,
    )
    folds = assess_folds(intervals, request)
    assert len(folds) == 3
    assert [fold.test_diagnostic.mean for fold in folds if fold.test_diagnostic] == [
        Decimal("0.05"),
        Decimal("0.08"),
        Decimal("0.11"),
    ]
    assert folds[0].walk_forward.train == (0, 1)
    assert folds[0].purged.purged == (2, 6)
    assert folds[0].purged.embargoed == (7,)
    altered = (intervals[0].model_copy(update={"net_return": Decimal("0.9")}), *intervals[1:])
    assert assess_folds(altered, request) == folds
    with pytest.raises(ValueError, match="contiguous"):
        assess_folds((intervals[0], *intervals[2:]), request)
