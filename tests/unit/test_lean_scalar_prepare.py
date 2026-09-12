"""Scalar translation carries declared sources and refuses unsupported execution semantics."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from test_monthly_admission import AT, MemoryStore, original_strategy

from infra.lean.execution.prepare import arithmetic_tree, build_files, build_strategy_files

REPO = Path(__file__).resolve().parents[2]


def test_whole_share_policy_is_transmitted_without_computed_targets() -> None:
    """The independent engine receives the declared policy and sources, never Python sizing."""
    spec, store = original_strategy()
    spec = spec.model_copy(
        update={
            "portfolio": spec.portfolio.model_copy(
                update={"quantity": "whole_shares_toward_zero_v1"}
            )
        }
    )
    files = build_strategy_files(REPO, store, spec, initial_cash=Decimal("1002"), evaluated_at=AT)
    source = json.loads(files["source.json"])
    assert source["schema_version"] == "original-lean-execution-v4"
    assert source["strategy"]["portfolio"]["quantity"] == "whole_shares_toward_zero_v1"
    assert set(source) == {
        "schema_version",
        "initial_cash_usd",
        "calendar",
        "strategy",
        "signals",
        "market",
        "expression",
    }


def test_scalar_translation_uses_source_sample_and_capital() -> None:
    """Different sample windows and cash need no C# source changes or expected NAV input."""
    spec, store = original_strategy()
    short = build_strategy_files(REPO, store, spec, initial_cash=Decimal("501"), evaluated_at=AT)
    long = build_files(REPO, MemoryStore())
    first, second = (json.loads(files["source.json"]) for files in (short, long))
    assert first["initial_cash_usd"] == "501"
    assert first["strategy"]["evaluation"]["sample_end"] == "2024-05-03"
    assert second["strategy"]["evaluation"]["sample_end"] == "2024-05-16"
    assert set(first) == {
        "schema_version",
        "initial_cash_usd",
        "calendar",
        "strategy",
        "signals",
        "market",
        "expression",
    }
    assert first["calendar"] == json.loads(store.get(spec.timing.calendar))
    assert short == build_strategy_files(
        REPO, store, spec, initial_cash=Decimal("501"), evaluated_at=AT
    )


@pytest.mark.parametrize("kind", ["formula", "cash", "tamper"])
def test_unsupported_or_corrupt_translation_is_rejected(kind: str) -> None:
    """The translator cannot silently erase richer formulas or bypass artifact admission."""
    spec, store = original_strategy()
    if kind == "formula":
        spec = spec.model_copy(update={"formula": "delta(score)"})
    if kind == "tamper":
        store.values[spec.market.table.artifact.sha256] = b"{}"
    from factorforge.domain.errors import ResearchError

    with pytest.raises((ValueError, ResearchError)):
        build_strategy_files(
            REPO,
            store,
            spec,
            initial_cash=Decimal("0") if kind == "cash" else Decimal("1002"),
            evaluated_at=AT,
        )


def test_arithmetic_translation_preserves_literals_and_rejects_time_series_calls() -> None:
    """The wire contains operations and source names, never evaluated factor scores."""
    tree = arithmetic_tree("(3/4)*score + (1/4)*quality")
    assert tree["kind"] == "add"
    assert arithmetic_tree("0.10000000000000000000001") == {
        "kind": "number",
        "numerator": "10000000000000000000001",
        "denominator": "100000000000000000000000",
    }
    for expression in ("delta(score)", "compound_return(score, 3)"):
        with pytest.raises(ValueError, match="time-series"):
            arithmetic_tree(expression)
