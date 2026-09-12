"""A longer executed market path supplies actual fold inputs and explicit transaction costs."""

from decimal import Decimal
from pathlib import Path

from test_monthly_admission import AT, MemoryStore

from factorforge.backtests.monthly import run_monthly
from factorforge.data.validation_fixture import prepare_validation_fixture
from factorforge.validation.research import ValidationRequest, validate_research


def test_twelve_executed_returns_feed_three_validation_blocks() -> None:
    """Ten shares per leg cost $2 to enter and $2.11 to liquidate the final $2110 gross."""
    store = MemoryStore()
    spec = prepare_validation_fixture(Path(__file__).resolve().parents[2], store)
    run = run_monthly(spec, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)
    assert run.status == "completed", run.failure_code
    assert run.path is not None
    assert [row.nav_usd for row in run.path.closes] == list(
        map(
            Decimal,
            [
                "1020",
                "1010",
                "1040",
                "1030",
                "1060",
                "1050",
                "1080",
                "1070",
                "1100",
                "1090",
                "1120",
                "1107.89",
            ],
        )
    )
    assert run.performance is not None
    assert run.performance.terminal_nav_usd == Decimal("1107.89")
    ref = store.put(run.canonical_bytes(), media_type="application/json")
    result = validate_research(
        ValidationRequest(
            result=ref,
            initial_train_size=3,
            test_size=3,
            hac_lags=1,
            embargo_seconds=86400,
        ),
        store,
    )
    assert result.reason is None
    assert len(result.periods) == 12
    assert len(result.folds) == 3
    for fold in result.folds:
        assert fold.reason is None
        assert fold.test_diagnostic is not None
        assert fold.test_diagnostic.request.values == tuple(
            run.performance.intervals[index].net_return for index in fold.walk_forward.test
        )
