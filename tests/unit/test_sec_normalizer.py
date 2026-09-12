"""Authored SEC-format responses test source identity and timing without claiming live ingestion."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_monthly_admission import MemoryStore

from factorforge.data.sec_normalizer import (
    FilingAvailability,
    SecNormalizationRequest,
    normalize_sec,
)
from factorforge.domain.errors import ResearchError
from factorforge.domain.monthly_signals import MonthlySourceBundle


def request(store: MemoryStore, *, timing: bool = True) -> SecNormalizationRequest:
    """Two filings retain an original instant and a later amended value for the same period."""
    source = store.put(
        json.dumps(
            dict(
                cik=320193,
                taxonomy="us-gaap",
                tag="Assets",
                units={
                    "USD": [
                        dict(
                            end="2024-03-31",
                            val=100,
                            accn="0000320193-24-000001",
                            filed="2024-05-01",
                            form="10-Q",
                        ),
                        dict(
                            end="2024-03-31",
                            val=110,
                            accn="0000320193-24-000002",
                            filed="2024-05-03",
                            form="10-Q/A",
                        ),
                    ]
                },
            )
        ).encode(),
        media_type="application/json",
    )
    evidence = store.put(b"controlled accession timing review", media_type="text/plain")
    return SecNormalizationRequest(
        source=source,
        cik="0000320193",
        taxonomy="us-gaap",
        tag="Assets",
        unit="USD",
        period_kind="instant",
        security_id="controlled-security",
        security_mapping=store.put(b"controlled CIK/security mapping", media_type="text/plain"),
        retrieved_at=datetime(2024, 6, 1, tzinfo=UTC),
        filed_from=date(2024, 5, 1),
        filed_through=date(2024, 5, 31),
        availability=tuple(
            FilingAvailability(
                accession=f"0000320193-24-{index:06}",
                available_at=datetime(2024, 5, day, 21, tzinfo=UTC),
                evidence=evidence,
            )
            for index, day in ((1, 1), (2, 3))
        )
        if timing
        else (),
    )


def test_revisions_are_preserved_and_prior_selection_excludes_later_filing() -> None:
    """Publication-time selection uses reviewed clocks and keeps both source accessions."""
    from factorforge.data.point_in_time import select_facts

    store = MemoryStore()
    value = request(store)
    result = normalize_sec(value, store)
    assert result.status == "ready" and result.emitted_rows == 2
    assert result.normalized is not None
    bundle = MonthlySourceBundle.model_validate_json(store.get(result.normalized))
    assert bundle.membership == ()
    assert [row.value for row in bundle.facts] == [Decimal(100), Decimal(110)]
    selected = select_facts(
        bundle.facts, datetime(2024, 5, 2, tzinfo=UTC), datetime(2024, 5, 2, 1, tzinfo=UTC)
    )
    assert len(selected) == 1 and selected[0].value == 100
    assert normalize_sec(value, store) == result


@pytest.mark.parametrize("partial", [False, True])
def test_missing_timing_holds_all_output(partial: bool) -> None:
    """A filed date is not promoted to an invented availability timestamp."""
    store = MemoryStore()
    value = request(store, timing=partial)
    if partial:
        value = value.model_copy(update={"availability": value.availability[:1]})
    result = normalize_sec(value, store)
    assert result.status == "held" and result.normalized is None and result.emitted_rows == 0
    assert len(result.unresolved_accessions) == (1 if partial else 2)


@pytest.mark.parametrize(
    "case", ["cik", "unit", "duration", "numeric", "conflict", "future_timing"]
)
def test_wrong_or_ambiguous_source_cannot_emit_facts(case: str) -> None:
    """Rows must satisfy the requested entity/context and preserve exact numeric values."""
    store = MemoryStore()
    value = request(store)
    wire = json.loads(store.get(value.source))
    if case == "cik":
        wire["cik"] = 1
    elif case == "unit":
        wire["units"] = {"shares": wire["units"]["USD"]}
    elif case == "duration":
        wire["units"]["USD"][0]["start"] = "2024-01-01"
    elif case == "numeric":
        wire["units"]["USD"][0]["val"] = True
    elif case == "conflict":
        wire["units"]["USD"].append({**wire["units"]["USD"][0], "val": 99})
    else:
        wire["units"]["USD"][0]["filed"] = "2024-05-02"
    ref = store.put(json.dumps(wire).encode(), media_type="application/json")
    with pytest.raises(ResearchError):
        normalize_sec(value.model_copy(update={"source": ref}), store)


def test_exact_source_decimal_survives_json_parsing() -> None:
    """Fractional XBRL values must not pass through binary float rounding."""
    store = MemoryStore()
    value = request(store)
    raw = store.get(value.source).replace(b'"val": 100', b'"val": 0.10000000000000000000001')
    ref = store.put(raw, media_type="application/json")
    result = normalize_sec(value.model_copy(update={"source": ref}), store)
    assert result.normalized is not None
    bundle = MonthlySourceBundle.model_validate_json(store.get(result.normalized))
    assert bundle.facts[0].value == Decimal("0.10000000000000000000001")


def test_duration_period_and_empty_window_are_explicit() -> None:
    """Duration starts survive conversion; a scoped window with no rows emits no source."""
    store = MemoryStore()
    value = request(store)
    wire = json.loads(store.get(value.source))
    for row in wire["units"]["USD"]:
        row["start"] = "2024-01-01"
    ref = store.put(json.dumps(wire).encode(), media_type="application/json")
    result = normalize_sec(
        value.model_copy(update={"source": ref, "period_kind": "duration"}), store
    )
    assert result.normalized is not None
    bundle = MonthlySourceBundle.model_validate_json(store.get(result.normalized))
    assert all(row.period_start == date(2024, 1, 1) for row in bundle.facts)
    empty = normalize_sec(value.model_copy(update={"filed_from": date(2024, 5, 20)}), store)
    assert empty.reason == "empty_window" and empty.selected_rows == 0 and empty.normalized is None
    scoped = normalize_sec(value.model_copy(update={"filed_through": date(2024, 5, 1)}), store)
    assert (scoped.input_rows, scoped.selected_rows, scoped.emitted_rows) == (2, 1, 1)


def test_capture_clock_and_result_scope_cannot_be_rewritten() -> None:
    """Future evidence fails admission; a held receipt cannot be relabeled ready."""
    store = MemoryStore()
    value = request(store)
    with pytest.raises(ResearchError):
        normalize_sec(
            value.model_copy(update={"retrieved_at": datetime(2024, 4, 1, tzinfo=UTC)}), store
        )
    held = normalize_sec(request(store, timing=False), store)
    with pytest.raises(ValidationError):
        type(held).model_validate(held.model_copy(update={"status": "ready"}))


@pytest.mark.parametrize("kind", ["tamper", "timing_tamper", "duplicate_key", "extreme_decimal"])
def test_source_integrity_and_parser_bounds(kind: str) -> None:
    """Corrupt archives and ambiguous or oversized numeric tokens never emit a normalized table."""
    store = MemoryStore()
    value = request(store)
    raw = store.get(value.source)
    if kind == "tamper":
        store.values[value.source.sha256] = b"changed"
    elif kind == "timing_tamper":
        store.values[value.availability[0].evidence.sha256] = b"changed"
    else:
        raw = (
            raw.replace(b'"cik": 320193', b'"cik": 1, "cik": 320193')
            if kind == "duplicate_key"
            else raw.replace(b'"val": 100', b'"val": 1e-1000000000')
        )
        value = value.model_copy(update={"source": store.put(raw, media_type="application/json")})
    with pytest.raises(ResearchError):
        normalize_sec(value, store)
