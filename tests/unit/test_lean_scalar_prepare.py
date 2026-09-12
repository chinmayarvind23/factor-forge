"""Scalar translation carries declared sources and refuses unsupported execution semantics."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from test_monthly_admission import AT, MemoryStore, original_strategy

from infra.lean.execution.prepare import build_files, build_strategy_files

REPO = Path(__file__).resolve().parents[2]


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
        spec = spec.model_copy(update={"formula": "score * 2"})
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
