"""Raw prices, separate action coverage and borrow grants remain explicit execution inputs."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.raw_market import load_intervals, load_market
from factorforge.domain.accounting import CorporateAction
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_market import (
    BorrowGrant,
    IntervalReturn,
    IntervalSource,
    MarketQuote,
    RawMarketSource,
)


def instant(day: int, hour: int = 20) -> datetime:
    """Original UTC clocks cover one sample without relying on an exchange calendar."""
    return datetime(2024, 5, day, hour, tzinfo=UTC)


def quote(**changes: object) -> MarketQuote:
    """A contemporaneous raw USD close is input data, not a generated execution fill."""
    return MarketQuote.model_validate(
        {
            "source_id": "close-A",
            "security_id": "A",
            "phase": "close",
            "observed_at": instant(1),
            "available_at": instant(1),
            "price_usd": Decimal(100),
            "adjustment": "unadjusted",
            "currency": "USD",
        }
        | changes
    )


def grant(**changes: object) -> BorrowGrant:
    """A grant states an original zero-fee loan limit over a closed observation interval."""
    return BorrowGrant.model_validate(
        {
            "source_id": "loan-A",
            "security_id": "A",
            "available_at": instant(1, 9),
            "valid_from": instant(1, 9),
            "valid_through": instant(3),
            "maximum_short_shares": Decimal(10),
            "annual_borrow_bps": 0,
            "permission": "original_fixture_short_loan",
        }
        | changes
    )


def market(**changes: object) -> RawMarketSource:
    """Coverage is an authored assertion; the executor must still match every calendar clock."""
    return RawMarketSource.model_validate(
        {
            "coverage_start": instant(1, 9),
            "coverage_end": instant(3),
            "security_ids": ("A",),
            "quotes": (quote(),),
            "actions": (),
            "borrow_grants": (grant(),),
            "corporate_action_coverage": "complete_explicit_events",
            "terminal_exit_coverage": "complete_explicit_events",
        }
        | changes
    )


def test_raw_source_round_trip_preserves_prices_and_empty_action_assertion() -> None:
    """Canonical source bytes retain decimal strings and the distinct no-events assertion."""
    value = market()
    assert RawMarketSource.model_validate_json(value.canonical_bytes()) == value
    assert value.quotes[0].ledger_mark().price_usd == Decimal(100)
    assert value.actions == ()
    assert value.terminal_exit_coverage == "complete_explicit_events"


@pytest.mark.parametrize(
    "changes",
    [
        {"security_ids": ("B",)},
        {"security_ids": ("A", "A")},
        {"quotes": (quote(), quote(source_id="duplicate-clock"))},
        {"quotes": (quote(), quote(observed_at=instant(2)))},
        {"borrow_grants": (grant(), grant())},
        {"quotes": (quote(observed_at=instant(4)),)},
        {"coverage_end": instant(1, 8)},
        {"corporate_action_coverage": "unknown"},
    ],
)
def test_ambiguous_or_uncovered_market_inventory_fails(changes: dict[str, object]) -> None:
    """Conflicting observations and missing event-coverage declarations cannot be repaired."""
    with pytest.raises(ValidationError):
        market(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_through": instant(1, 8)},
        {"maximum_short_shares": Decimal(0)},
        {"maximum_short_shares": Decimal("0.0000000000000000001")},
        {"annual_borrow_bps": 1},
        {"annual_borrow_bps": False},
        {"permission": "membership_implies_borrow"},
    ],
)
def test_borrow_grant_requires_exact_explicit_supported_terms(changes: dict[str, object]) -> None:
    """The first zero-carry profile rejects alternative loan terms instead of ignoring them."""
    with pytest.raises(ValidationError):
        grant(**changes)


def test_availability_is_preserved_for_later_execution_admission() -> None:
    """Preserve late observations; execution must reject their use at an earlier clock."""
    value = market(quotes=(quote(available_at=instant(2)),))
    assert value.quotes[0].available_at > value.quotes[0].observed_at


def interval(**changes: object) -> IntervalReturn:
    """Reference return rows identify one series and one exact close-to-close interval."""
    return IntervalReturn.model_validate(
        {
            "source_id": "rf-1",
            "series_id": "risk_free",
            "start_at": instant(1),
            "end_at": instant(2),
            "available_at": instant(2),
            "cumulative_return": Decimal(0),
        }
        | changes
    )


def test_reference_series_never_imputes_missing_intervals() -> None:
    """Retain supplied rows only; execution checks complete calendar alignment."""
    value = IntervalSource(rows=(interval(), interval(source_id="bm-1", series_id="benchmark")))
    assert IntervalSource.model_validate_json(value.canonical_bytes()) == value
    assert len(value.rows) == 2
    with pytest.raises(ValidationError):
        IntervalSource(rows=(interval(), interval(source_id="duplicate")))


@pytest.mark.parametrize(
    "changes",
    [
        {"end_at": instant(1)},
        {"cumulative_return": Decimal("-1.01")},
        {"series_id": "anything"},
        {"cumulative_return": Decimal("1e-101")},
    ],
)
def test_reference_intervals_reject_invalid_arithmetic_and_roles(
    changes: dict[str, object],
) -> None:
    """Comparison series have declared return units, forward periods and bounded exact input."""
    with pytest.raises(ValidationError):
        interval(**changes)


def test_numeric_json_prices_and_forged_nested_values_fail() -> None:
    """Wire numbers cannot pass through float coercion, nor copied values bypass ledger bounds."""
    raw = market().canonical_bytes().replace(b'"price_usd":"100"', b'"price_usd":100')
    with pytest.raises(ValidationError):
        RawMarketSource.model_validate_json(raw)
    with pytest.raises(ValidationError):
        market(quotes=(quote().model_copy(update={"price_usd": Decimal("1e25")}),))


def test_verified_loaders_read_exact_source_bytes() -> None:
    """Loading authenticates content identity before interpreting original fixture observations."""
    with TemporaryDirectory(prefix="factorforge-raw-source-") as directory:
        store = LocalArtifactStore(Path(directory))
        prices = market()
        rates = IntervalSource(rows=(interval(),))
        assert (
            load_market(store.put(prices.canonical_bytes(), media_type="application/json"), store)
            == prices
        )
        assert (
            load_intervals(store.put(rates.canonical_bytes(), media_type="application/json"), store)
            == rates
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"rows":[],"rows":[]}',
        b'{"rows":NaN}',
        b'{"rows":null}',
        b'{"rows":[' + b"{}," * 1022 + b"{}]}",
        b'{"rows":[],"nested":' + b"[" * 18 + b"0" + b"]" * 18 + b"}",
        b'{"rows":[],"nested":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}",
    ],
)
def test_loader_rejects_duplicate_fields_and_resource_overruns(raw: bytes) -> None:
    """Malformed and oversized structures fail before they can select a value or nested row."""
    with TemporaryDirectory(prefix="factorforge-raw-source-") as directory:
        store = LocalArtifactStore(Path(directory))
        ref = store.put(raw, media_type="application/json")
        with pytest.raises(ResearchError) as failure:
            load_intervals(ref, store)
        assert failure.value.code == "RAW_SOURCE_INVALID"


def test_loader_preflights_size_and_media_without_reading_missing_objects() -> None:
    """Invalid declarations fail before object-store I/O or raw body allocation."""
    with TemporaryDirectory(prefix="factorforge-raw-source-") as directory:
        store = LocalArtifactStore(Path(directory))
        for size, media in ((8 * 1024 * 1024 + 1, "application/json"), (2, "text/plain")):
            with pytest.raises(ResearchError) as failure:
                load_market(ArtifactRef(sha256="0" * 64, size_bytes=size, media_type=media), store)
            assert failure.value.code == "RAW_SOURCE_LIMIT"


def test_unknown_exit_remains_explicit_source_data() -> None:
    """Keeping an unknown exit in the source lets execution reject it instead of inventing cash."""
    event = CorporateAction(
        event_id="exit-A",
        security_id="A",
        kind="terminal_exit",
        available_at=instant(2),
        effective_at=instant(2),
        pay_at=None,
        cash_per_share=None,
        old_shares=None,
        new_shares=None,
    )
    value = market(actions=(event,))
    assert RawMarketSource.model_validate_json(value.canonical_bytes()).actions == (event,)
    with pytest.raises(ValidationError):
        market(actions=(event, event))
    with pytest.raises(ValidationError):
        market(actions=(event.model_copy(update={"effective_at": instant(4)}),))


def test_contract_inventory_limits_and_security_patterns_are_enforced() -> None:
    """Copied source models still enforce inventory and identifier bounds."""
    for changes in (
        {"security_ids": ()},
        {"security_ids": ("../A",)},
        {"security_ids": tuple(str(i) for i in range(9))},
        {"quotes": (quote(),) * 8193},
        {"borrow_grants": (grant(),) * 2049},
    ):
        with pytest.raises(ValidationError):
            market(**changes)


def test_loader_does_not_trust_storage_success_without_matching_bytes() -> None:
    """A provider returning wrong bytes is rejected before source parsing succeeds."""

    class CorruptStore:
        """A deliberately dishonest provider probes the independent loader integrity boundary."""

        def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
            """This read-only probe must never be asked to publish data."""
            raise AssertionError("Unexpected publication")

        def get(self, ref: ArtifactRef) -> bytes:
            """Return a valid-looking body with an identity different from the requested object."""
            return b'{"rows":[]}'

    ref = ArtifactRef(sha256="0" * 64, size_bytes=11, media_type="application/json")
    with pytest.raises(ResearchError) as failure:
        load_intervals(ref, CorruptStore())
    assert failure.value.code == "ARTIFACT_INTEGRITY"
