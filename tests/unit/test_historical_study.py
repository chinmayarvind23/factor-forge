"""Hand portfolios and future perturbations constrain the retrospective research study."""

from typing import Any

import pytest

from factorforge.evaluation.historical_study import (
    SIGNALS,
    annualized_sharpe,
    period_return,
    signal_score,
)


@pytest.mark.parametrize("signal", SIGNALS)
def test_signal_never_reads_beyond_formation(signal: str) -> None:
    """Changing every later observation cannot alter an already formed signal."""
    closes = [float(100 + i * i) for i in range(30)]
    daily = [0.01 + i / 1000 for i in range(30)]
    expected = signal_score(signal, closes, daily, 15)
    assert signal_score(signal, closes[:16] + [1e6] * 14, daily[:16] + [100] * 14, 15) == expected


def test_round_trip_fees_and_drift_match_hand_account() -> None:
    """A flat fully liquidated 200% gross portfolio pays both entry and exit costs."""
    net, _, fee = period_return({"A": 1, "B": -1}, {}, {"A": 0, "B": 0}, 10, terminal=True)
    assert net == pytest.approx(-0.004)
    assert fee == pytest.approx(0.004)
    net, drift, fee = period_return({"A": 1, "B": -1}, {}, {"A": 0.1, "B": -0.1}, 0, terminal=False)
    assert net == pytest.approx(0.2)
    assert drift == pytest.approx({"A": 1.1 / 1.2, "B": -0.9 / 1.2})
    assert fee == 0


def test_turnover_uses_drifted_positions() -> None:
    """Unchanged target ranks can still require trades after asymmetric price moves."""
    target = {"A": 1.0, "B": -1.0}
    _, old, _ = period_return(target, {}, {"A": 0.1, "B": 0}, 0, terminal=False)
    _, _, fee = period_return(target, old, {"A": 0, "B": 0}, 10, terminal=False)
    assert fee == pytest.approx(0.001 * (1 - 1 / 1.1))


def test_momentum_skip_and_reversal_have_declared_direction() -> None:
    """A last-month price jump changes reversal but cannot enter skip-month momentum."""
    prices = [100.0] * 15
    prices[12] = 120
    assert signal_score("momentum_12_skip1", prices, [0.0] * 15, 12) == 0
    assert signal_score("reversal_1", prices, [0.0] * 15, 12) == pytest.approx(-0.2)


def test_constant_returns_have_no_sharpe() -> None:
    """Valid flat portfolios remain completed experiments with an unavailable statistic."""
    assert annualized_sharpe([0.0] * 100) is None


def test_failed_experiment_is_retained_and_next_case_can_run() -> None:
    """A failed numerical case gets a durable summary without cancelling the remaining inventory."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from factorforge.evaluation.historical_study import _retain_failure

    summaries: list[dict[str, Any]] = []
    with TemporaryDirectory() as directory:
        with _retain_failure(summaries, "first", 0, Path(directory)):
            raise ValueError("controlled")
        with _retain_failure(summaries, "second", 0, Path(directory)):
            summaries.append({"signal": "second", "status": "completed"})
        assert (Path(directory) / "first-0.json").exists()
    assert [row["status"] for row in summaries] == ["failed", "completed"]
