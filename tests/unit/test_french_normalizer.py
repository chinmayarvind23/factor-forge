"""Authored daily CSV cases constrain exact return units, coverage and archive boundaries."""

import io
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from test_monthly_admission import AT, MemoryStore, original_strategy
from test_monthly_backtest import execute, replace_source

from factorforge.data.french_normalizer import FrenchDailyRequest, normalize_french_daily
from factorforge.domain.calendar import SessionCalendar
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_market import IntervalSource
from factorforge.lineage.closure import verify_closure


def request(
    store: MemoryStore, body: str = "20240103,1.20,0.1,0.2,0.02\n20240104,-2,0,0,0.01"
) -> FrenchDailyRequest:
    """A known two-interval archive includes an unused first-day return for the baseline."""
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "F-F_Research_Data_Factors_daily.csv",
            "Source preamble\n,Mkt-RF,SMB,HML,RF\n20240102,0,0,0,0\n"
            + body
            + "\n\nCopyright notice\n",
        )
    return FrenchDailyRequest(
        source=store.put(raw.getvalue(), media_type="application/zip"),
        acquisition=store.put(b"controlled acquisition receipt", media_type="text/plain"),
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
        session_closes=tuple(datetime(2024, 1, day, 21, tzinfo=UTC) for day in (2, 3, 4)),
    )


def test_exact_market_total_returns_and_replay() -> None:
    """Market return adds RF to Mkt-RF before percentage conversion; capture is availability."""
    store = MemoryStore()
    req = request(store)
    result = normalize_french_daily(req, store)
    rows = IntervalSource.model_validate_json(store.get(result.normalized)).rows
    assert [row.cumulative_return for row in rows] == [
        Decimal("0.0122"),
        Decimal("0.0002"),
        Decimal("-0.0199"),
        Decimal("0.0001"),
    ]
    assert all(row.available_at == req.retrieved_at for row in rows)
    assert result.input_rows == 3
    assert result.emitted_rows == 4
    assert normalize_french_daily(req, store) == result
    root = store.put(result.canonical_bytes(), media_type="application/json")
    verify_closure(root, store)


@pytest.mark.parametrize(
    "body",
    [
        "20240103,-99.99,0,0,0\n20240104,0,0,0,0",
        "20240103,NaN,0,0,0\n20240104,0,0,0,0",
        "20240103,1e200,0,0,0\n20240104,0,0,0,0",
        "20240103,0,0,0,0\n20240103,0,0,0,0\n20240104,0,0,0,0",
        "20240104,0,0,0,0",
        "20240103,0,0,0,0\n20240104,-101,0,0,0",
        "20240103,0,0,0,0\n20240104,0,0,0",
    ],
)
def test_invalid_or_incomplete_source_cannot_emit(body: str) -> None:
    """Missing values, invented numeric formats and incomplete calendars cannot become zeros."""
    store = MemoryStore()
    with pytest.raises(ResearchError):
        normalize_french_daily(request(store, body), store)


def test_calendar_cannot_skip_a_source_trading_date() -> None:
    """A requested multi-day interval must not be mistaken for a single daily return."""
    store = MemoryStore()
    req = request(store)
    req = req.model_copy(update={"session_closes": (req.session_closes[0], req.session_closes[2])})
    with pytest.raises(ResearchError):
        normalize_french_daily(req, store)


def test_source_corruption_is_detected() -> None:
    """Transport output is independently checked before opening an archive."""
    store = MemoryStore()
    req = request(store)
    store.values[req.source.sha256] = b"tampered"
    with pytest.raises(ResearchError):
        normalize_french_daily(req, store)


@pytest.mark.parametrize("case", ["deflate", "path", "multiple", "compression"])
def test_archive_failures_are_typed(case: str) -> None:
    """Malformed compression and unexpected members cannot escape the bounded import contract."""
    store = MemoryStore()
    req = request(store)
    if case == "deflate":
        raw = bytearray(store.get(req.source))
        offset = 30 + int.from_bytes(raw[26:28], "little") + int.from_bytes(raw[28:30], "little")
        raw[offset] = 0xFF
        data = bytes(raw)
    else:
        output = io.BytesIO()
        compression = zipfile.ZIP_BZIP2 if case == "compression" else zipfile.ZIP_STORED
        with zipfile.ZipFile(output, "w", compression=compression) as archive:
            name = "../source.csv" if case == "path" else "F-F_Research_Data_Factors_daily.csv"
            archive.writestr(name, "invalid source")
            if case == "multiple":
                archive.writestr("other.csv", "unexpected")
        data = output.getvalue()
    req = req.model_copy(update={"source": store.put(data, media_type="application/zip")})
    with pytest.raises(ResearchError) as caught:
        normalize_french_daily(req, store)
    assert caught.value.code == "FRENCH_NORMALIZATION_INVALID"


@pytest.mark.parametrize("late", [False, True])
def test_normalized_comparison_is_consumed_at_evaluation_time(late: bool) -> None:
    """Authored provider-shaped returns exercise the actual engine's ex-post availability gate."""
    spec, store = original_strategy()
    calendar = SessionCalendar.model_validate_json(store.get(spec.timing.calendar))
    clocks = tuple(
        row.closes_at
        for row in calendar.sessions
        if spec.evaluation.sample_start <= row.session_date <= spec.evaluation.sample_end
    )
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr(
            "F-F_Research_Data_Factors_daily.csv",
            ",Mkt-RF,SMB,HML,RF\n" + "\n".join(f"{at:%Y%m%d},0,0,0,0" for at in clocks),
        )
    req = FrenchDailyRequest(
        source=store.put(raw.getvalue(), media_type="application/zip"),
        acquisition=store.put(b"authored provider receipt", media_type="text/plain"),
        retrieved_at=AT + timedelta(seconds=1 if late else 0),
        session_closes=clocks,
    )
    normalized = normalize_french_daily(req, store)
    intervals = IntervalSource.model_validate_json(store.get(normalized.normalized))

    def replace_intervals(value: dict[str, Any]) -> None:
        """Bind controlled normalized rows through the production manifest path."""
        value.update(intervals.model_dump(mode="json"))

    spec = replace_source(spec, store, "intervals", replace_intervals)
    result = execute(spec, store)
    if late:
        assert result.failure_code == "MONTHLY_COMPARISON_INTERVAL_UNAVAILABLE"
    else:
        assert result.status == "completed", result.failure_code
        assert result.benchmark is not None
