"""Original monthly facts test publication, economic periods and immutable selected provenance."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from pydantic import ValidationError

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.monthly_signals import assemble_monthly_signals, civil_month_cutoff
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import FormationPlan
from factorforge.domain.errors import ResearchError
from factorforge.domain.monthly_signals import (
    MonthlyAssembly,
    MonthlyBinding,
    MonthlySelection,
    MonthlySignalRequest,
    MonthlySourceBundle,
)


def instant(value: str) -> datetime:
    """Parse authored UTC event times without inferring provider publication times."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def request(
    month: int = 4, *, history: int = 1, capitalization: bool = False
) -> MonthlySignalRequest:
    """Bind explicit instant concepts and a calendar identity for one authored formation."""
    formation = "2024-04-30T20:00:00Z" if month == 4 else "2024-05-31T20:00:00Z"
    trade = "2024-05-01T13:30:00Z" if month == 4 else "2024-06-03T13:30:00Z"
    bindings = tuple(
        MonthlyBinding(
            name=name,
            concept=name,
            unit="dimensionless",
            history_observations=history,
            frequency="monthly",
            period_context="instant",
        )
        for name in ("numerator", "denominator")
    )
    cap = (
        MonthlyBinding(
            name="cap",
            concept="market_cap",
            unit="USD",
            history_observations=1,
            frequency="monthly",
            period_context="instant",
        )
        if capitalization
        else None
    )
    return MonthlySignalRequest(
        formation=FormationPlan(
            calendar_sha256="a" * 64, formation_at=instant(formation), trade_at=instant(trade)
        ),
        formula="numerator / denominator",
        formation_lag_months=0,
        bindings=bindings,
        capitalization_binding=cap,
        freshness="explicit_requested_calendar_month_no_stale_fallback_v1",
        revision_policy="latest_available_then_revision_reject_conflicts",
    )


def source() -> dict[str, Any]:
    """Supply original input-only facts including revisions, unrelated durations and a late row."""
    facts = []
    for security, april, may in (("SEC-A", "10", "20"), ("SEC-H", "80", "90")):
        for month, numerator in ((4, april), (5, may)):
            end = "2024-04-30" if month == 4 else "2024-05-31"
            for concept, value, unit in (
                ("numerator", numerator, "dimensionless"),
                ("denominator", "10", "dimensionless"),
                ("market_cap", "100", "USD"),
            ):
                available = end + "T20:00:00Z"
                if security == "SEC-H" and month == 5 and concept == "numerator":
                    available = "2024-06-03T12:00:00Z"
                facts.append(
                    dict(
                        security_id=security,
                        concept=concept,
                        period_end=end,
                        period_start=None,
                        value=value,
                        unit=unit,
                        available_at=available,
                        source_id=f"SRC-{security}-{month}",
                        revision=0,
                    )
                )
    facts.extend(
        [
            facts[0]
            | {
                "value": "999",
                "source_id": "RESTATEMENT-1",
                "revision": 1,
                "available_at": "2024-05-01T12:00:00Z",
            },
            facts[0]
            | {
                "value": "888",
                "source_id": "RESTATEMENT-2",
                "revision": 2,
                "available_at": "2024-05-31T19:30:00Z",
            },
            facts[0] | {"value": "777", "source_id": "DURATION", "period_start": "2024-04-01"},
        ]
    )
    members = [
        dict(
            security_id=security,
            event_id="shared-announcement",
            included=True,
            effective_at="2024-04-01T13:30:00Z",
            available_at="2024-03-28T12:00:00Z",
        )
        for security in ("SEC-A", "SEC-H")
    ]
    return {"schema_version": "monthly-source-v1", "facts": facts, "membership": members}


@pytest.mark.parametrize("month", [4, 5])
def test_actual_formation_publication_and_requested_period_control_selection(month: int) -> None:
    """Later publications and older periods cannot replace the required formation-month facts."""
    with TemporaryDirectory(prefix="factorforge-monthly-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(json.dumps(source()).encode(), media_type="application/json")
        result = assemble_monthly_signals(ref, store, request(month))
        values = {row.security_id: row.signal for row in result.cross_section.observations}
        assert values == (
            {"SEC-A": "1", "SEC-H": "8"} if month == 4 else {"SEC-A": "2", "SEC-H": None}
        )
        assert result.cross_section.universe == ("SEC-A", "SEC-H")
        assert result.cross_section.source_refs == (ref,)
        selected = [
            row
            for row in result.selections
            if row.binding_name == "numerator" and row.fact.security_id == "SEC-A"
        ]
        assert selected[0].fact.source_id == f"SRC-SEC-A-{month}"


def test_multiple_revisions_never_satisfy_a_missing_consecutive_month() -> None:
    """Missing March remains missing despite several available April revisions."""
    with TemporaryDirectory(prefix="factorforge-monthly-history-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(json.dumps(source()).encode(), media_type="application/json")
        result = assemble_monthly_signals(ref, store, request(history=2))
        assert all(row.signal is None for row in result.cross_section.observations)
        assert len(result.missing) == 4
        assert {row.requested_month for row in result.missing} == {date(2024, 3, 1)}


@pytest.mark.parametrize(
    ("day", "lag", "expected"),
    [
        ("2024-05-31", 1, "2024-04-30"),
        ("2024-04-30", 1, "2024-03-30"),
        ("2024-03-31", 1, "2024-02-29"),
        ("2024-06-28", 0, "2024-06-28"),
    ],
)
def test_civil_month_cutoff_preserves_day_and_clamps_only_when_necessary(
    day: str, lag: int, expected: str
) -> None:
    """No requested economic cutoff expands to an unobserved future month end."""
    assert civil_month_cutoff(date.fromisoformat(day), lag) == date.fromisoformat(expected)


def assembled(
    payload: dict[str, Any], query: MonthlySignalRequest | None = None
) -> MonthlyAssembly:
    """Each test stores exactly its raw input-only bytes before invoking production assembly."""
    with TemporaryDirectory(prefix="factorforge-monthly-probe-") as directory:
        store = LocalArtifactStore(Path(directory))
        reference = store.put(json.dumps(payload).encode(), media_type="application/json")
        return assemble_monthly_signals(reference, store, query or request())


@pytest.mark.parametrize(
    "case",
    [
        "conflict",
        "old_conflict",
        "ambiguous_month",
        "zero_denominator",
        "bad_cap",
        "return_below_minus_one",
    ],
)
def test_corrupt_selected_inputs_are_failures_not_missing_exclusions(case: str) -> None:
    """Conflicts and invalid arithmetic cannot be repaired by another period or source."""
    payload = source()
    query = request()
    expected = "DATA_CONFLICT"
    if case in {"conflict", "old_conflict"}:
        bad = payload["facts"][0] | {"value": "55"}
        if case == "old_conflict":
            payload["facts"][0]["period_end"] = "2024-03-31"
            bad["period_end"] = "2024-03-31"
        payload["facts"].append(bad)
    elif case == "ambiguous_month":
        payload["facts"].append(
            payload["facts"][0] | {"source_id": "OTHER-DAY", "period_end": "2024-04-29"}
        )
        expected = "MONTHLY_PERIOD_AMBIGUOUS"
    elif case == "zero_denominator":
        payload["facts"][1]["value"] = "0"
        expected = "FORMULA_ZERO_DIVISION"
    elif case == "bad_cap":
        payload["facts"][2]["value"] = "-1"
        query = request(capitalization=True)
        expected = "MONTHLY_CAPITALIZATION_INVALID"
    else:
        query = query.model_copy(
            update={
                "formula": "numerator",
                "bindings": (query.bindings[0].model_copy(update={"unit": "return_decimal"}),),
            }
        )
        payload["facts"][0].update(unit="return_decimal", value="-1.01")
        expected = "MONTHLY_RETURN_INVALID"
    with pytest.raises(ResearchError) as caught:
        assembled(payload, query)
    assert caught.value.code == expected


def test_equal_weight_request_does_not_require_or_use_capitalization() -> None:
    """An input needed only for weighting cannot exclude a valid equal-weight signal."""
    payload = source()
    payload["facts"] = [row for row in payload["facts"] if row["concept"] != "market_cap"]
    equal = assembled(payload)
    assert all(
        row.signal is not None and row.capitalization is None
        for row in equal.cross_section.observations
    )
    value = assembled(payload, request(capitalization=True))
    assert all(
        row.signal is not None and row.capitalization is None
        for row in value.cross_section.observations
    )
    assert {item.binding_name for item in value.missing} == {"cap"}


def test_monthly_compounding_uses_oldest_to_newest_complete_return_history() -> None:
    """Two consecutive months compound as decimal total returns without annual inference."""
    payload = source()
    payload["facts"] = [
        payload["facts"][0]
        | {"period_end": end, "value": value, "unit": "return_decimal", "source_id": end}
        for end, value in (("2024-03-31", "0.1"), ("2024-04-30", "-0.1"))
    ]
    base = request(history=2)
    query = base.model_copy(
        update={
            "formula": "compound_return(numerator, 2)",
            "bindings": (base.bindings[0].model_copy(update={"unit": "return_decimal"}),),
        }
    )
    result = assembled(payload, query)
    assert Decimal(result.cross_section.observations[0].signal or "NaN") == Decimal("-0.01")
    assert [row.fact.period_end for row in result.selections] == [
        date(2024, 3, 31),
        date(2024, 4, 30),
    ]
    assert result.cross_section.observations[1].signal is None


@pytest.mark.parametrize(
    "case",
    [
        "delta",
        "unknown_name",
        "history",
        "units",
        "duration",
        "duplicate_binding",
        "cap_units",
        "syntax",
        "folded_time",
    ],
)
def test_forged_request_cannot_bypass_monthly_binding_contract(case: str) -> None:
    """Copied requests still require explicit monthly context, closed names and causal clocks."""
    base = request()
    changes: dict[str, Any] = {}
    if case == "delta":
        changes = {"formula": "delta(numerator) / denominator"}
    elif case == "unknown_name":
        changes = {"formula": "unknown / denominator"}
    elif case in {"history", "units"}:
        changes = {"formula": "compound_return(numerator, 2) / denominator"}
        if case == "history":
            changes["bindings"] = (
                base.bindings[0].model_copy(update={"unit": "return_decimal"}),
                base.bindings[1],
            )
    elif case == "duration":
        changes = {
            "bindings": (
                base.bindings[0].model_copy(update={"period_context": "duration"}),
                base.bindings[1],
            )
        }
    elif case == "duplicate_binding":
        changes = {"bindings": (base.bindings[0], base.bindings[0])}
    elif case == "cap_units":
        changes = {"capitalization_binding": base.bindings[0].model_copy(update={"name": "cap"})}
    elif case == "syntax":
        changes = {"formula": "__import__('os')"}
    else:
        changes = {
            "formation": base.formation.model_copy(update={"trade_at": base.formation.formation_at})
        }
    with pytest.raises(ResearchError) as caught:
        assembled(source(), base.model_copy(update=changes))
    assert caught.value.code == "MONTHLY_REQUEST_INVALID"


@pytest.mark.parametrize(
    "case",
    [
        "extra_gold",
        "nonfinite",
        "huge_decimal",
        "naive",
        "utc_overflow",
        "duration_reversed",
        "row_bound",
    ],
)
def test_source_model_rejects_invalid_rows_before_period_filtering(case: str) -> None:
    """Raw row corruption does not disappear merely because it is outside the selected month."""
    payload = source()
    if case == "extra_gold":
        payload["expected_signals"] = {"SEC-A": "1"}
    elif case == "nonfinite":
        payload["facts"][0]["value"] = "NaN"
    elif case == "huge_decimal":
        payload["facts"][0]["value"] = "1e101"
    elif case == "naive":
        payload["facts"][0]["available_at"] = "2024-04-30T20:00:00"
    elif case == "utc_overflow":
        payload["facts"][0]["available_at"] = "0001-01-01T00:00:00+14:00"
    elif case == "duration_reversed":
        payload["facts"][0]["period_start"] = "2024-05-01"
    else:
        payload["facts"] = payload["facts"][:1] * 50001
    with pytest.raises(ResearchError) as caught:
        assembled(payload)
    assert caught.value.code in {"MONTHLY_SOURCE_INVALID", "MONTHLY_SOURCE_LIMIT"}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"monthly-source-v1","facts":[],"facts":[],"membership":[]}',
        b'{"facts":NaN}',
        b'"' + b"x" * 100 + b'"',
        b"[" * 100 + b"]" * 100,
        b"\xff",
    ],
)
def test_raw_json_rejects_duplicate_nonfinite_deep_and_invalid_documents(raw: bytes) -> None:
    """The byte parser rejects ambiguity before Pydantic sees the source document."""
    with TemporaryDirectory(prefix="factorforge-monthly-json-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(raw, media_type="application/json")
        with pytest.raises(ResearchError) as caught:
            assemble_monthly_signals(ref, store, request())
        assert caught.value.code == "MONTHLY_SOURCE_INVALID"


def test_source_and_request_hashes_change_with_actual_input_choices() -> None:
    """Raw ordering changes source identity while economic selection remains deterministic."""
    original = assembled(source())
    payload = source()
    payload["facts"].reverse()
    payload["membership"].reverse()
    reordered = assembled(payload)
    assert reordered.source_ref.sha256 != original.source_ref.sha256
    assert reordered.cross_section.observations == original.cross_section.observations
    assert reordered.selections == original.selections
    assert reordered.request_sha256 == original.request_sha256
    assert MonthlyAssembly.model_validate_json(original.canonical_bytes()) == original


@pytest.mark.parametrize("case", ["lost_cell", "wrong_cutoff"])
def test_saved_receipt_cannot_drop_a_requested_cell_or_change_cutoff(case: str) -> None:
    """A complete receipt retains every month and the cutoff derived from its request."""
    result = assembled(source())
    value = result.model_dump()
    if case == "lost_cell":
        value["selections"] = result.selections[:-1]
    else:
        value["economic_cutoff"] = date(2024, 5, 1)
    with pytest.raises(ValidationError):
        MonthlyAssembly.model_validate(value)


@pytest.mark.parametrize("case", ["signal", "cap", "missing_signal"])
def test_saved_scalars_must_follow_selected_facts_and_missing_history(case: str) -> None:
    """A selected-source receipt cannot relabel its signal or erase its required missing month."""
    result = assembled(source(), request(5 if case == "missing_signal" else 4, capitalization=True))
    value = result.model_dump(mode="json")
    target = value["cross_section"]["observations"][-1 if case == "missing_signal" else 0]
    target["capitalization" if case == "cap" else "signal"] = "999"
    with pytest.raises(ValidationError):
        MonthlyAssembly.model_validate_json(json.dumps(value))


def test_missing_cap_history_cannot_hide_a_known_negative_capitalization() -> None:
    """A missing month cannot convert another required corrupt value into an exclusion."""
    payload = source()
    payload["facts"][2]["value"] = "-1"
    query = request(capitalization=True)
    assert query.capitalization_binding is not None
    query = query.model_copy(
        update={
            "capitalization_binding": query.capitalization_binding.model_copy(
                update={"history_observations": 2}
            )
        }
    )
    with pytest.raises(ResearchError) as caught:
        assembled(payload, query)
    assert caught.value.code == "MONTHLY_CAPITALIZATION_INVALID"


class UnreadStore:
    """Preflight failures must happen before any source byte read or artifact mutation."""

    def get(self, ref: ArtifactRef) -> bytes:
        """A read proves the resource preflight was incorrectly deferred."""
        raise AssertionError("Unexpected source read")

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """Assembly has no need to mutate its source storage."""
        raise AssertionError("Unexpected write")


@pytest.mark.parametrize("case", ["bytes", "media"])
def test_source_limit_is_checked_before_io(case: str) -> None:
    """Metadata cannot authorize reading an oversized or unsupported source representation."""
    ref = ArtifactRef(
        sha256="b" * 64,
        size_bytes=9 * 1024 * 1024 if case == "bytes" else 0,
        media_type="application/json" if case == "bytes" else "text/plain",
    )
    with pytest.raises(ResearchError) as caught:
        assemble_monthly_signals(ref, UnreadStore(), request())
    assert caught.value.code == "MONTHLY_SOURCE_LIMIT"


def test_tampered_source_bytes_fail_integrity_before_selection() -> None:
    """The receipt source identity must bind the actual bytes that reach the selector."""
    with TemporaryDirectory(prefix="factorforge-monthly-tamper-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(json.dumps(source()).encode(), media_type="application/json")
        path = Path(directory) / "sha256" / ref.sha256[:2] / ref.sha256
        path.write_bytes(b"tampered")
        with pytest.raises(ResearchError) as caught:
            assemble_monthly_signals(ref, store, request())
        assert caught.value.code == "ARTIFACT_INTEGRITY"


def test_requested_cell_budget_precedes_fact_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A large cross-product is rejected before source selection or per-cell materialization."""
    payload = source()
    member = payload["membership"][0]
    payload["membership"] = [member | {"security_id": f"SEC-{i}"} for i in range(1000)]

    def forbidden(*args: object, **kwargs: object) -> None:
        """Any fact selection means the requested-work preflight ran too late."""
        raise AssertionError("Unexpected fact indexing")

    monkeypatch.setattr("factorforge.data.monthly_signals.select_facts", forbidden)
    with pytest.raises(ResearchError) as caught:
        assembled(payload, request(history=120))
    assert caught.value.code == "MONTHLY_WORK_LIMIT"


def test_no_historical_eligible_security_is_an_explicit_failure() -> None:
    """The assembler does not invent a universe from whichever fact rows happen to exist."""
    payload = source()
    payload["membership"] = []
    with pytest.raises(ResearchError) as caught:
        assembled(payload)
    assert caught.value.code == "MONTHLY_EMPTY_UNIVERSE"


@pytest.mark.parametrize("case", ["lag_bool", "underflow", "wrong_date_type"])
def test_civil_cutoff_invalid_arguments_are_typed(case: str) -> None:
    """Civil arithmetic has a bounded domain and does not accept datetime or boolean coercion."""
    day: Any = date(1, 1, 1) if case == "underflow" else date(2024, 4, 30)
    lag: Any = True if case == "lag_bool" else 1
    if case == "wrong_date_type":
        day = instant("2024-04-30T20:00:00Z")
    with pytest.raises(ResearchError) as caught:
        civil_month_cutoff(day, lag)
    assert caught.value.code == "MONTHLY_REQUEST_INVALID"


@pytest.mark.parametrize("case", ["fact_nan", "fact_utc", "member_utc"])
def test_forged_c4_models_are_reconstructed_before_source_serialization(case: str) -> None:
    """C4's default instance-validation policy cannot leak forged rows into an artifact receipt."""
    bundle = MonthlySourceBundle.model_validate_json(json.dumps(source()), strict=True)
    from datetime import timedelta, timezone

    impossible = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14)))
    if case.startswith("fact"):
        fact = bundle.facts[0].model_copy(
            update={"value": Decimal("NaN")} if case == "fact_nan" else {"available_at": impossible}
        )
        forged = bundle.model_copy(update={"facts": (fact,)})
    else:
        member = bundle.membership[0].model_copy(update={"effective_at": impossible})
        forged = bundle.model_copy(update={"membership": (member,)})
    with pytest.raises(ValidationError):
        forged.canonical_bytes()


def test_lagged_economic_period_uses_latest_publication_known_by_actual_formation() -> None:
    """Economic lag changes the requested month while the information clock stays at formation."""
    query = request(5).model_copy(update={"formation_lag_months": 1})
    result = assembled(source(), query)
    assert result.economic_cutoff == date(2024, 4, 30)
    assert result.cross_section.observations[0].signal == "88.8"
    numerator = next(
        row
        for row in result.selections
        if row.binding_name == "numerator" and row.fact.security_id == "SEC-A"
    )
    assert numerator.fact.source_id == "RESTATEMENT-2"


@pytest.mark.parametrize(
    "case",
    [
        "request_hash",
        "source_ref",
        "observation_inventory",
        "duplicate_cell",
        "selected_unit",
        "selected_future",
        "selected_zero_denominator",
        "selected_negative_cap",
    ],
)
def test_saved_receipt_rejects_forged_lineage_and_selected_economics(case: str) -> None:
    """Receipt reload validates identity closure and selected-row interpretation before hashing."""
    result = assembled(source(), request(capitalization=True))
    value = result.model_dump(mode="json")
    if case == "request_hash":
        value["request_sha256"] = "e" * 64
    elif case == "source_ref":
        value["source_ref"]["sha256"] = "e" * 64
    elif case == "observation_inventory":
        value["cross_section"]["observations"].pop()
    elif case == "duplicate_cell":
        value["selections"].append(value["selections"][0])
    else:
        name = (
            "denominator"
            if case == "selected_zero_denominator"
            else "cap"
            if case == "selected_negative_cap"
            else "numerator"
        )
        row = next(item for item in value["selections"] if item["binding_name"] == name)
        if case == "selected_unit":
            row["fact"]["unit"] = "USD"
        elif case == "selected_future":
            row["fact"]["available_at"] = "2024-05-01T12:00:00Z"
        else:
            row["fact"]["value"] = "0" if case == "selected_zero_denominator" else "-1"
    with pytest.raises(ValidationError):
        MonthlyAssembly.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("token", ["1.00000000000000000001", "1"])
def test_json_decimal_values_require_text_before_numeric_coercion(token: str) -> None:
    """A raw number cannot round away source digits before the exact-decimal field is validated."""
    raw = json.dumps(source()).replace('"value": "10"', '"value": ' + token, 1).encode()
    with pytest.raises(ValidationError):
        MonthlySourceBundle.model_validate_json(raw, strict=True)
    with TemporaryDirectory(prefix="factorforge-monthly-numeric-wire-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(raw, media_type="application/json")
        with pytest.raises(ResearchError) as caught:
            assemble_monthly_signals(ref, store, request())
        assert caught.value.code == "MONTHLY_SOURCE_INVALID"


def test_selection_receipt_wire_values_preserve_the_same_decimal_text_rule() -> None:
    """Selected provenance cannot reintroduce rounded numeric JSON values on reload."""
    row = assembled(source()).selections[0]
    raw = row.model_dump_json().replace('"value":"10"', '"value":1.00000000000000000001')
    with pytest.raises(ValidationError):
        MonthlySelection.model_validate_json(raw, strict=True)
    assert MonthlySelection.model_validate(row).fact.value == Decimal(10)
