"""The admitted engine must reproduce frozen original chronology without consuming its oracle."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from test_monthly_admission import AT, MemoryStore, changed_manifest, original_strategy

from factorforge.backtests import monthly
from factorforge.backtests.monthly import MonthlyPrepared, MonthlyRun, run_monthly
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import SessionCalendar
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec


def replace_source(
    spec: RawStrategySpec, store: MemoryStore, role: str, change: Callable[[dict[str, Any]], None]
) -> RawStrategySpec:
    """Author a separate test source and manifest without modifying frozen fixture files."""
    reference = {
        "signals": spec.universe.table.artifact,
        "market": spec.market.table.artifact,
        "intervals": spec.evaluation.benchmark.table.artifact,
    }[role]
    value = json.loads(store.values[reference.sha256])
    change(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    replaced = store.put(raw, media_type="application/json")
    manifest = json.loads(store.values[spec.datasets[0].manifest.sha256])
    count = {
        "signals": lambda: len(value["facts"]) + len(value["membership"]),
        "market": lambda: sum(len(value[key]) for key in ("quotes", "actions", "borrow_grants")),
        "intervals": lambda: len(value["rows"]),
    }[role]()
    for item in manifest["objects"]:
        if item["name"] == role:
            item.update(artifact=replaced.model_dump(), row_count=count)
    spec = changed_manifest(spec, store, objects=manifest["objects"])
    wire = spec.model_dump(mode="json")
    for binding in (
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ):
        if binding["table"]["object_name"] == role:
            binding["table"]["artifact"] = replaced.model_dump()
    return RawStrategySpec.model_validate_json(json.dumps(wire))


def execute(spec: RawStrategySpec, store: MemoryStore) -> MonthlyRun:
    """Negative cases retain the same explicit positive-fee capital denominator."""
    return run_monthly(spec, store, initial_cash_usd=Decimal("1002"), evaluated_at=AT)


@pytest.mark.parametrize("scenario", ["fees", "rank_reversal", "unchanged_ranks"])
def test_unchanged_inventory_reuses_ledger_and_matches_full_replay(scenario: str) -> None:
    """Every valuation matches independent full replay while only trades rebuild the ledger."""
    from unittest.mock import patch

    from factorforge.backtests import accounting

    spec, store = original_strategy() if scenario == "fees" else two_formation_strategy()
    capital = Decimal("1002" if scenario == "fees" else "1000")
    if scenario == "unchanged_ranks":

        def keep_ranks(value: dict[str, Any]) -> None:
            """A zero-turnover formation still records a batch without changing inventory."""
            for row in value["facts"]:
                if row["source_id"].startswith("may-score-"):
                    row["value"] = "2" if row["security_id"] == "A" else "1"

        spec = replace_source(spec, store, "signals", keep_ranks)
    with patch.object(accounting, "_replay", wraps=accounting._replay) as replay:
        result = run_monthly(spec, store, initial_cash_usd=capital, evaluated_at=AT)
        calls = replay.call_count
    assert result.status == "completed", result.failure_code
    assert calls == 1 + sum(bool(batch.fill_ids) for batch in result.batches)
    if scenario == "unchanged_ranks":
        assert len(result.batches) == 3
        assert result.batches[1].fill_ids == ()
    assert calls < len(result.observations)
    for observation in result.observations:
        # Before-entry marks precede same-instant fills; recorded phases identify that boundary.
        ids = {phase.event_id for phase in observation.snapshot.applied_phases}
        expected = accounting.account_at(
            initial_cash=capital,
            start_at=result.observations[0].at,
            at=observation.at,
            fills=tuple(fill for fill in result.fills if fill.fill_id in ids),
            actions=(),
            marks=observation.marks,
            costs=spec.costs,
        )
        assert observation.snapshot == expected


def test_frozen_original_trace_and_metrics_follow_actual_strategy_inputs() -> None:
    """PIT selection, generated fills, funding and complete metrics reproduce independent gold."""
    spec, store = original_strategy()
    result = run_monthly(
        spec,
        store,
        initial_cash_usd=Decimal("1002"),
        evaluated_at=datetime(2026, 9, 11, tzinfo=UTC),
    )
    assert result.status == "completed", result.failure_code
    expected = Path(__file__).parents[2] / "data/backtests/monthly-raw-v1/expected"
    trace = json.loads((expected / "trace.json").read_bytes())
    metrics = json.loads((expected / "metrics.json").read_bytes())
    assert len(result.observations) == len(trace["observations"])
    for observed, gold in zip(result.observations, trace["observations"], strict=True):
        assert observed.at.isoformat().replace("+00:00", "Z") == gold["at"]
        assert Fraction(observed.snapshot.nav_usd) == Fraction(gold["nav_usd"])
        assert Fraction(observed.snapshot.cash_usd) == Fraction(gold["cash_usd"])
        assert observed.collateral.free_cash_usd.as_fraction() == Fraction(gold["free_cash_usd"])
    assert len(result.batches) == 2
    assert [fill.signed_quantity for fill in result.fills] == [10, -10, -10, 10]
    assert {row.fact.source_id for row in result.formations[0].assembly.selections} == {
        "score-A",
        "score-B",
    }
    assert result.performance is not None and result.benchmark is not None
    assert result.performance.n == metrics["n_intervals"]
    assert Fraction(result.performance.terminal_nav_usd) == Fraction(metrics["terminal_nav_usd"])
    for actual, key in (
        (result.performance.total_return, "total_return"),
        (result.performance.daily_net_mean, "mean_net"),
        (result.performance.net_sharpe, "annualized_sharpe"),
        (result.performance.max_drawdown, "max_drawdown_closes"),
        (result.performance.turnover, "total_turnover"),
    ):
        assert actual.value is not None
        assert abs(actual.value - Decimal(metrics[key]["decimal_50"])) < Decimal("1e-40")
    assert result.benchmark.net_sharpe.status == "unavailable"
    assert result.prepared_ref is not None


def test_nonterminating_quantity_stops_before_any_generated_fill() -> None:
    """A rational funding root cannot be rounded into the existing exact share contract."""
    spec, store = original_strategy()
    result = run_monthly(
        spec,
        store,
        initial_cash_usd=Decimal("1000"),
        evaluated_at=datetime(2026, 9, 11, tzinfo=UTC),
    )
    assert result.status == "failed" and result.performance is None
    assert result.fills == ()
    assert result.failure_code == "FUNDING_QUANTITY_PRECISION"


@pytest.mark.parametrize("change", ["missing", "late", "expired", "insufficient", "ambiguous"])
def test_short_permission_must_be_known_unique_active_and_sufficient(change: str) -> None:
    """Membership never grants a loan and no later permission silently repairs an entry."""
    spec, store = original_strategy()

    def mutate(value: dict[str, Any]) -> None:
        """Each original negative scenario changes one declared loan condition."""
        grant = value["borrow_grants"][0]
        if change == "missing":
            value["borrow_grants"] = []
        elif change == "ambiguous":
            value["borrow_grants"].append(grant | {"source_id": "second-grant"})
        elif change == "late":
            grant["available_at"] = "2024-05-01T13:30:01Z"
        elif change == "expired":
            grant["valid_through"] = "2024-05-01T13:29:59Z"
        else:
            grant["maximum_short_shares"] = "9"

    spec = replace_source(spec, store, "market", mutate)
    result = execute(spec, store)
    assert result.status == "failed"
    assert result.failure_code == "MONTHLY_BORROW_UNAVAILABLE_OR_AMBIGUOUS"
    assert result.fills == () and result.batches == ()
    assert len(result.formations) == 1 and result.performance is None


def test_expired_held_loan_stops_at_first_required_observation() -> None:
    """An entry permission cannot keep a short open beyond its recorded finite term."""
    spec, store = original_strategy()
    spec = replace_source(
        spec,
        store,
        "market",
        lambda value: value["borrow_grants"][0].update(valid_through="2024-05-01T14:00:00Z"),
    )
    result = execute(spec, store)
    assert result.failure_code == "MONTHLY_BORROW_EXPIRED_OR_INSUFFICIENT"
    assert result.failure_at == datetime(2024, 5, 1, 20, tzinfo=UTC)
    assert len(result.fills) == 2 and result.performance is None


@pytest.mark.parametrize("change", ["missing", "late", "wrong_phase"])
def test_missing_held_close_does_not_shorten_sample(change: str) -> None:
    """Unavailable raw prices produce a failed declared denominator rather than a shorter path."""
    spec, store = original_strategy()

    def mutate(value: dict[str, Any]) -> None:
        """Replace one held closing quote without changing the calendar inventory."""
        rows = value["quotes"]
        target = next(
            row
            for row in rows
            if row["security_id"] == "A" and row["observed_at"] == "2024-05-02T20:00:00Z"
        )
        if change == "missing":
            rows.remove(target)
        elif change == "late":
            target["available_at"] = "2024-05-02T20:00:01Z"
        else:
            target["phase"] = "open"

    spec = replace_source(spec, store, "market", mutate)
    result = execute(spec, store)
    assert result.failure_code == "MONTHLY_QUOTE_MISSING_OR_UNAVAILABLE"
    assert result.failure_at == datetime(2024, 5, 2, 20, tzinfo=UTC)
    assert len(result.session_closes) == 4 and len(result.batches) == 1
    assert result.path is None and result.performance is None


def test_short_drift_retains_failed_reserve_without_auto_liquidation() -> None:
    """Positive NAV cannot override negative free cash at a required open observation."""
    spec, store = original_strategy()

    def mutate(value: dict[str, Any]) -> None:
        """The original adverse path raises one short quote above its reserved cash."""
        for row in value["quotes"]:
            if row["security_id"] == "B" and row["observed_at"] == "2024-05-02T13:30:00Z":
                row["price_usd"] = "101"

    spec = replace_source(spec, store, "market", mutate)
    result = execute(spec, store)
    assert result.failure_code == "FUNDING_COLLATERAL_DEFICIT"
    observed = result.observations[-1]
    assert observed.snapshot.nav_usd > 0
    assert observed.collateral.free_cash_usd.as_fraction() == -10
    assert len(result.fills) == 2 and result.performance is None


@pytest.mark.parametrize("change", ["missing", "late", "misaligned"])
def test_comparison_intervals_must_cover_the_actual_complete_path(change: str) -> None:
    """A completed ledger cannot manufacture an unavailable benchmark or risk-free interval."""
    spec, store = original_strategy()

    def mutate(value: dict[str, Any]) -> None:
        """Keep the reference contract valid while breaking actual path coverage or knowledge."""
        if change == "missing":
            value["rows"].pop()
        elif change == "late":
            value["rows"][0]["available_at"] = "2027-01-01T00:00:00Z"
        else:
            value["rows"][0]["start_at"] = "2024-04-30T19:00:00Z"

    spec = replace_source(spec, store, "intervals", mutate)
    result = execute(spec, store)
    assert result.failure_code == "MONTHLY_COMPARISON_INTERVAL_UNAVAILABLE"
    assert result.performance is None and result.status == "failed"


def test_admission_failure_retains_request_before_source_interpretation() -> None:
    """A corrupt provider cannot produce a prepared or completed economic run."""
    spec, store = original_strategy()
    store.values[spec.market.table.artifact.sha256] = b"corrupt"
    result = execute(spec, store)
    assert result.status == "failed" and result.prepared_ref is None
    assert result.fills == () and result.formations == ()
    assert result.request_ref.sha256 in store.values


def test_prepared_publication_precedes_loop_and_failure_preserves_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected calculation fault retains its actual prepared inputs and controller code."""
    spec, store = original_strategy()

    def broken_loop(state: object) -> None:
        """The controlled test fault occurs only after all preparation artifacts were published."""
        assert any(
            raw.startswith(b'{"') and b'"monthly-backtest-prepared-v1"' in raw
            for raw in store.values.values()
        )
        raise RuntimeError("private fault must not enter result")

    monkeypatch.setattr(monthly, "_loop", broken_loop)
    result = execute(spec, store)
    assert result.failure_code == "MONTHLY_EXECUTION_FAILED"
    assert result.prepared_ref is not None
    prepared = MonthlyPrepared.model_validate_json(store.values[result.prepared_ref.sha256])
    assert len(prepared.code) == len(monthly.CODE_FILES)
    assert all("expected" not in row.module for row in prepared.code)
    assert prepared.environment_ref.sha256 in store.values
    assert b"private fault" not in result.canonical_bytes()


def test_failed_prepared_publication_prevents_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure to publish the pre-calculation receipt is a hard boundary, not optional logging."""
    spec, store = original_strategy()
    put = store.put

    def rejected(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Only the prepared artifact fails so terminal failure evidence remains publishable."""
        if data.startswith(b'{"') and b'"monthly-backtest-prepared-v1"' in data:
            raise ResearchError("ARTIFACT_WRITE_FAILED", "Unavailable", 503)
        return put(data, media_type=media_type)

    def forbidden(state: object) -> None:
        """No signal or account work is authorized before prepared publication succeeds."""
        raise AssertionError("Loop must not run")

    monkeypatch.setattr(store, "put", rejected)
    monkeypatch.setattr(monthly, "_loop", forbidden)
    result = execute(spec, store)
    assert result.failure_code == "ARTIFACT_WRITE_FAILED" and result.prepared_ref is None


def test_saved_run_cannot_forge_completed_status_or_drop_fills() -> None:
    """Terminal status and fill inventories remain checked when a result is copied or reloaded."""
    spec, store = original_strategy()
    result = execute(spec, store)
    assert MonthlyRun.model_validate_json(result.canonical_bytes()) == result
    for changes in ({"fills": ()}, {"performance": None}, {"failure_code": "error"}):
        with pytest.raises(ValidationError):
            result.model_copy(update=changes).canonical_bytes()


@pytest.mark.parametrize("change", ["empty", "missing_close", "changed_nav"])
def test_completed_metrics_require_the_retained_account_observations(change: str) -> None:
    """Completed metrics cannot survive removal or replacement of the account path they describe."""
    spec, store = original_strategy()
    result = execute(spec, store)
    updates: dict[str, object]
    if change == "empty":
        updates = {"observations": ()}
    elif change == "missing_close":
        updates = {
            "observations": tuple(row for row in result.observations if row.phase != "close")
        }
    else:
        assert result.path is not None
        path = result.path.model_copy(
            update={
                "closes": tuple(
                    row.model_copy(update={"nav_usd": cast(Decimal, row.nav_usd) + Decimal(1)})
                    for row in result.path.closes
                )
            }
        )
        assert result.performance is not None
        updates = {
            "path": path,
            "performance": result.performance.model_copy(update={"path_sha256": path.sha256}),
        }
    with pytest.raises(ValidationError):
        result.model_copy(update=updates).canonical_bytes()


@pytest.mark.parametrize(
    "change",
    ["batch_clock", "batch_amount", "request_metadata", "formation_source", "missing_prepared"],
)
def test_saved_result_cannot_rebind_its_economic_or_source_evidence(change: str) -> None:
    """Copied records retain exact inputs, clocks, generated trades and preparation."""
    spec, store = original_strategy()
    result = execute(spec, store)
    if change in {"batch_clock", "batch_amount"}:
        batch = result.batches[0]
        execution = batch.execution.model_copy(
            update=(
                {"executed_at": datetime(2024, 5, 2, 13, 30, tzinfo=UTC)}
                if change == "batch_clock"
                else {"absolute_notional_usd": Decimal(1)}
            )
        )
        result = result.model_copy(
            update={
                "batches": (
                    batch.model_copy(update={"execution": execution}),
                    *result.batches[1:],
                )
            }
        )
    elif change == "request_metadata":
        result = result.model_copy(
            update={"request_ref": result.request_ref.model_copy(update={"size_bytes": 1})}
        )
    elif change == "formation_source":
        formation = result.formations[0]
        new_request = formation.assembly.request.model_copy(update={"formula": "score + 0"})
        assembly = formation.assembly.model_copy(
            update={
                "request": new_request,
                "request_sha256": new_request.sha256,
            }
        )
        result = result.model_copy(
            update={"formations": (formation.model_copy(update={"assembly": assembly}),)}
        )
    else:
        result = result.model_copy(
            update={
                "status": "failed",
                "failure_code": "error",
                "prepared_ref": None,
                "path": None,
                "performance": None,
                "benchmark_path": None,
                "benchmark": None,
            }
        )
    with pytest.raises(ValidationError):
        result.canonical_bytes()


def test_output_store_cannot_relabel_json_as_another_media_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published request identity includes media metadata as well as matching content bytes."""
    spec, store = original_strategy()
    put = store.put

    def dishonest(data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """The negative transport preserves the hash while falsifying its interpretation."""
        return put(data, media_type=media_type).model_copy(update={"media_type": "text/plain"})

    monkeypatch.setattr(store, "put", dishonest)
    with pytest.raises(ResearchError, match="Monthly strategy"):
        execute(spec, store)


def two_formation_strategy() -> tuple[RawStrategySpec, MemoryStore]:
    """A separate original constant-price path reverses ranks at a later monthly formation."""
    spec, store = original_strategy()
    calendar = json.loads(store.values[spec.timing.calendar.sha256])
    day = date(2024, 6, 4)
    while day <= date(2024, 7, 1):
        if day.weekday() < 5:
            calendar["sessions"].append(
                {
                    "session_date": day.isoformat(),
                    "opens_at": f"{day}T13:30:00Z",
                    "closes_at": f"{day}T20:00:00Z",
                }
            )
        day += timedelta(days=1)
    calendar["coverage_end"] = "2024-07-01"
    parsed = SessionCalendar.model_validate_json(json.dumps(calendar))
    calendar_ref = store.put(parsed.canonical_bytes(), media_type="application/json")
    wire = spec.model_dump(mode="json")
    wire["timing"]["calendar"] = calendar_ref.model_dump()
    wire["evaluation"]["sample_end"] = "2024-06-04"
    wire["costs"].update(commission_bps=0, slippage_bps=0)
    spec = RawStrategySpec.model_validate_json(json.dumps(wire))
    spec = changed_manifest(spec, store, coverage_end="2024-06-04")
    sessions = [
        row for row in parsed.sessions if date(2024, 4, 30) <= row.session_date <= date(2024, 6, 4)
    ]

    def signals(value: dict[str, Any]) -> None:
        """The later formation has a newly known monthly observation for both securities."""
        for security, score in (("A", "1"), ("B", "2")):
            value["facts"].append(
                {
                    "available_at": "2024-05-31T12:00:00Z",
                    "concept": "original-score",
                    "period_end": "2024-05-31",
                    "period_start": None,
                    "revision": 0,
                    "security_id": security,
                    "source_id": f"may-score-{security}",
                    "unit": "dimensionless",
                    "value": score,
                }
            )

    def market(value: dict[str, Any]) -> None:
        """Constant available prices make the later signed reconstitution hand-checkable."""
        value["coverage_end"] = "2024-06-04T20:00:00Z"
        prototype = value["quotes"][0]
        value["quotes"] = [
            prototype
            | {
                "source_id": f"{row.session_date}-{phase}-{security}",
                "security_id": security,
                "phase": phase,
                "observed_at": at.isoformat(),
                "available_at": at.isoformat(),
                "price_usd": "100",
            }
            for row in sessions
            for phase, at in (("open", row.opens_at), ("close", row.closes_at))
            for security in ("A", "B")
            if at >= sessions[0].closes_at
        ]
        grant = value["borrow_grants"][0]
        value["borrow_grants"] = [
            grant
            | {
                "source_id": f"grant-{security}",
                "security_id": security,
                "valid_through": "2024-06-04T20:00:00Z",
            }
            for security in ("A", "B")
        ]

    def intervals(value: dict[str, Any]) -> None:
        """Both comparison series cover every real calendar interval through the later sample."""
        value["rows"] = [
            {
                "source_id": f"{series}-{index}",
                "series_id": series,
                "start_at": before.closes_at.isoformat(),
                "end_at": after.closes_at.isoformat(),
                "available_at": after.closes_at.isoformat(),
                "cumulative_return": "0",
            }
            for index, (before, after) in enumerate(pairwise(sessions))
            for series in ("benchmark", "risk_free")
        ]

    for role, change in (("signals", signals), ("market", market), ("intervals", intervals)):
        spec = replace_source(spec, store, role, change)
    return spec, store


def test_calendar_driven_second_formation_reverses_real_holdings() -> None:
    """Two monthly decisions drive separate exact batches without fixture offsets."""
    spec, store = two_formation_strategy()
    result = run_monthly(spec, store, initial_cash_usd=Decimal("1000"), evaluated_at=AT)
    assert result.status == "completed", result.failure_code
    assert len(result.formations) == 2 and len(result.batches) == 3
    assert [row.signed_quantity for row in result.fills] == [10, -10, -20, 20, 10, -10]
    assert result.batches[1].at == datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    assert result.performance is not None and result.performance.terminal_nav_usd == 1000
    assert result.performance.net_sharpe.status == "unavailable"
    assert result.performance.turnover.value == 8


def test_second_formation_liquidates_a_security_outside_the_new_universe() -> None:
    """Historical membership removal closes the old holding rather than losing its liability."""
    spec, store = two_formation_strategy()

    def signals(value: dict[str, Any]) -> None:
        """At the later formation C replaces A in the two-ID historical eligible universe."""
        value["facts"].append(
            value["facts"][-1]
            | {
                "security_id": "C",
                "value": "1",
                "source_id": "may-score-C",
            }
        )
        for security, included in (("A", False), ("C", True)):
            value["membership"].append(
                {
                    "available_at": "2024-05-31T12:00:00Z",
                    "effective_at": "2024-05-31T12:00:00Z",
                    "security_id": security,
                    "included": included,
                    "event_id": "universe-v2",
                }
            )

    def market(value: dict[str, Any]) -> None:
        """C has independently declared prices and a loan before it can become a target short."""
        value["security_ids"].append("C")
        value["quotes"] += [
            row | {"security_id": "C", "source_id": row["source_id"] + "-C"}
            for row in value["quotes"]
            if row["security_id"] == "B"
        ]
        value["borrow_grants"].append(
            value["borrow_grants"][0]
            | {
                "security_id": "C",
                "source_id": "grant-C",
            }
        )

    spec = replace_source(spec, store, "signals", signals)
    spec = replace_source(spec, store, "market", market)
    result = run_monthly(spec, store, initial_cash_usd=Decimal("1000"), evaluated_at=AT)
    assert result.status == "completed", result.failure_code
    assert [(row.security_id, row.signed_quantity) for row in result.fills] == [
        ("A", Decimal(10)),
        ("B", Decimal(-10)),
        ("A", Decimal(-10)),
        ("B", Decimal(20)),
        ("C", Decimal(-10)),
        ("B", Decimal(-10)),
        ("C", Decimal(10)),
    ]
    assert result.formations[1].assembly.cross_section.universe == ("B", "C")


def test_zero_weight_interior_security_needs_no_execution_quote() -> None:
    """An explicitly neutral interior bucket does not invent a fill or require an unused price."""
    spec, store = original_strategy()

    def signals(value: dict[str, Any]) -> None:
        """The third original scalar occupies the interior of three ordered buckets."""
        value["facts"].append(
            value["facts"][0]
            | {
                "source_id": "score-C",
                "security_id": "C",
                "value": "1.5",
            }
        )
        value["membership"].append(value["membership"][0] | {"security_id": "C"})

    spec = replace_source(spec, store, "signals", signals)
    spec = replace_source(spec, store, "market", lambda value: value["security_ids"].append("C"))
    spec = spec.model_copy(
        update={
            "portfolio": spec.portfolio.model_copy(
                update={
                    "allocation": spec.portfolio.allocation.model_copy(update={"bucket_count": 3}),
                }
            )
        }
    )
    result = execute(spec, store)
    assert result.status == "completed", result.failure_code
    assert all(row.security_id != "C" for row in result.fills)


def test_explicit_actions_stop_before_first_signal_or_fill() -> None:
    """The raw-price profile cannot silently ignore even a fully declared corporate event."""
    spec, store = original_strategy()
    action = {
        "event_id": "unknown-exit",
        "security_id": "A",
        "kind": "terminal_exit",
        "available_at": "2024-05-01T12:00:00Z",
        "effective_at": "2024-05-02T13:30:00Z",
        "pay_at": None,
        "old_shares": None,
        "new_shares": None,
        "cash_per_share": None,
    }
    spec = replace_source(spec, store, "market", lambda value: value["actions"].append(action))
    result = execute(spec, store)
    assert result.failure_code == "MONTHLY_ACTIONS_UNSUPPORTED"
    assert result.fills == () and result.formations == ()


@pytest.mark.parametrize("change", ["baseline", "terminal", "early_evaluation", "market_coverage"])
def test_declared_complete_sample_cannot_drift_to_available_rows(change: str) -> None:
    """Calendar baseline, terminal date and actual market bounds stay independent of outcomes."""
    spec, store = original_strategy()
    if change == "baseline":
        spec = spec.model_copy(
            update={
                "evaluation": spec.evaluation.model_copy(
                    update={
                        "sample_start": date(2024, 5, 1),
                    }
                )
            }
        )
    elif change == "terminal":
        spec = changed_manifest(spec, store, coverage_end="2024-05-04")
        spec = spec.model_copy(
            update={
                "evaluation": spec.evaluation.model_copy(
                    update={
                        "sample_end": date(2024, 5, 4),
                    }
                )
            }
        )
    elif change == "market_coverage":
        spec = replace_source(
            spec,
            store,
            "market",
            lambda value: value.update(
                coverage_start="2024-05-01T13:30:00Z",
                quotes=[
                    row for row in value["quotes"] if not row["observed_at"].startswith("2024-04")
                ],
            ),
        )
    result = run_monthly(
        spec,
        store,
        initial_cash_usd=Decimal("1002"),
        evaluated_at=(datetime(2024, 5, 2, tzinfo=UTC) if change == "early_evaluation" else AT),
    )
    assert result.status == "failed" and result.performance is None
    assert result.fills == ()


@pytest.mark.parametrize("cash", [True, "1002", Decimal("NaN"), Decimal("1e-100"), Decimal("1e25")])
def test_invalid_cash_never_reads_sources_or_publishes_request(cash: object) -> None:
    """Type and exact input precision validation precede all artifact operations."""
    spec, store = original_strategy()
    before = len(store.values)
    with pytest.raises(ResearchError):
        run_monthly(spec, store, initial_cash_usd=cash, evaluated_at=AT)  # type: ignore[arg-type]
    assert store.reads == [] and len(store.values) == before
