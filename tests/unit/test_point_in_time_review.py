"""Independent temporal probes reject order dependence and preserve accounting identities."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from factorforge.data.point_in_time import (
    FundamentalFact,
    MembershipEvent,
    select_facts,
    select_universe,
)
from factorforge.domain.errors import ResearchError

FORMATION = datetime(2024, 5, 1, 20, tzinfo=UTC)
TRADE = FORMATION + timedelta(hours=1)


def fact(
    source: str,
    *,
    concept: str = "assets",
    value: str = "100",
    available: datetime = FORMATION,
    revision: int = 0,
    unit: str = "USD",
) -> FundamentalFact:
    """Keep economic identity stable while varying source and publication metadata."""
    return FundamentalFact(
        security_id="SEC-A",
        concept=concept,
        period_end=date(2023, 12, 31),
        value=Decimal(value),
        unit=unit,
        available_at=available,
        source_id=source,
        revision=revision,
    )


def event(
    identifier: str, *, included: bool = True, when: datetime = FORMATION, security: str = "SEC-A"
) -> MembershipEvent:
    """An event identifies one security's inclusion decision within a supplied universe."""
    return MembershipEvent(
        security_id=security,
        event_id=identifier,
        included=included,
        effective_at=when,
        available_at=when,
    )


def test_accession_can_identify_multiple_concepts_and_units() -> None:
    """A filing document contains many facts; its accession is not a globally unique row ID."""
    rows = [
        fact("accession"),
        fact("accession", concept="liabilities", value="60"),
        fact("accession", unit="EUR", value="90"),
    ]
    assert set(select_facts(rows, FORMATION, TRADE)) == set(rows)


def test_explicit_revision_can_correct_same_document_fact() -> None:
    """Provider corrections need a new immutable revision even when the document stays the same."""
    old = fact("accession", available=FORMATION - timedelta(days=1))
    new = fact("accession", value="120", revision=1)
    assert select_facts([old, new], FORMATION, TRADE) == (new,)


def test_conflicting_superseded_facts_are_order_independent() -> None:
    """A latest publication cannot hide contradictory eligible history by arriving first."""
    old_time = FORMATION - timedelta(days=2)
    rows = [fact("a", available=old_time), fact("b", available=old_time, value="200"), fact("c")]
    for ordering in permutations(rows):
        with pytest.raises(ResearchError) as error:
            select_facts(ordering, FORMATION, TRADE)
        assert error.value.code == "DATA_CONFLICT"


def test_conflicting_superseded_membership_is_order_independent() -> None:
    """Conflicting known membership history cannot disappear behind a newer event."""
    old_time = FORMATION - timedelta(days=2)
    rows = [event("a", when=old_time), event("b", when=old_time, included=False), event("c")]
    for ordering in permutations(rows):
        with pytest.raises(ResearchError) as error:
            select_universe(ordering, FORMATION, TRADE)
        assert error.value.code == "DATA_CONFLICT"


def test_same_value_corroboration_uses_stable_provenance() -> None:
    """Matching reports do not become a numerical conflict due to their source ID."""
    rows = [fact("source-b"), fact("source-a")]
    for ordering in permutations(rows):
        assert select_facts(ordering, FORMATION, TRADE) == (rows[1],)


def test_one_membership_announcement_can_cover_multiple_securities() -> None:
    """A provider announcement ID can contain one membership event for each security."""
    rows = [event("rebalance", security="SEC-A"), event("rebalance", security="SEC-B")]
    assert select_universe(rows, FORMATION, TRADE) == ("SEC-A", "SEC-B")


def test_future_conflicts_cannot_rewrite_prior_selection() -> None:
    """Ignore future rows before resolving identity, including future changes to a reused source."""
    old = fact("accession")
    future = fact("accession", value="999", available=FORMATION + timedelta(seconds=1))
    assert select_facts([future, old], FORMATION, TRADE) == (old,)
    known = event("rebalance")
    future_event = event("rebalance", included=False, when=FORMATION + timedelta(seconds=1))
    assert select_universe([future_event, known], FORMATION, TRADE) == ("SEC-A",)


def test_dst_fold_uses_absolute_trade_order() -> None:
    """Same-zone wall clock comparisons ignore fold and can admit a trade before formation."""
    zone = ZoneInfo("America/New_York")
    later_formation = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=1)
    earlier_trade = datetime(2024, 11, 3, 1, 45, tzinfo=zone, fold=0)
    with pytest.raises(ResearchError):
        select_facts([], later_formation, earlier_trade)
    earlier_formation = later_formation.replace(fold=0)
    later_trade = earlier_trade.replace(fold=1, minute=15)
    assert select_facts([], earlier_formation, later_trade) == ()


def test_offset_equivalence_and_equal_availability_boundary() -> None:
    """Publication at formation is allowed and offset spelling cannot change that instant."""
    offset = FORMATION.astimezone(ZoneInfo("America/New_York"))
    row = fact("exact", available=offset)
    assert row.available_at == FORMATION
    assert select_facts([row], offset, TRADE) == (row,)


def test_invalid_period_and_nonfinite_values_rejected() -> None:
    """Forecast dates and invalid numeric values must never enter reported-fact selection."""
    values = fact("base").model_dump()
    with pytest.raises(ValidationError):
        FundamentalFact(**{**values, "period_end": date(2025, 1, 1)})
    for invalid in (Decimal("Infinity"), Decimal("-Infinity"), Decimal("NaN")):
        with pytest.raises(ValidationError):
            FundamentalFact(**{**values, "value": invalid})


def test_durations_and_instants_remain_distinct() -> None:
    """Identical period ends do not make annual, quarterly and instant observations equivalent."""
    instant = fact("filing", concept="revenue")
    annual = FundamentalFact(**{**instant.model_dump(), "period_start": date(2023, 1, 1)})
    quarter = FundamentalFact(**{**instant.model_dump(), "period_start": date(2023, 10, 1)})
    rows = [instant, annual, quarter]
    for ordering in permutations(rows):
        assert set(select_facts(ordering, FORMATION, TRADE)) == set(rows)
    with pytest.raises(ValidationError):
        FundamentalFact(**{**instant.model_dump(), "period_start": date(2024, 1, 1)})


def test_immutable_version_cannot_change_its_publication_time() -> None:
    """Changing a known source version's publication time requires an explicit new revision."""
    old = fact("filing", available=FORMATION - timedelta(days=1))
    changed = fact("filing")
    with pytest.raises(ResearchError, match="source identity"):
        select_facts([old, changed], FORMATION, TRADE)


def test_matching_membership_announcements_are_order_independent() -> None:
    """Equivalent announcements may corroborate the same effective membership decision."""
    for ordering in permutations([event("a"), event("b")]):
        assert select_universe(ordering, FORMATION, TRADE) == ("SEC-A",)


def test_revision_rank_is_secondary_to_publication_time() -> None:
    """A later document supersedes earlier revisions; a tied timestamp uses revision order."""
    old = fact("old", available=FORMATION - timedelta(days=1), revision=99)
    first = fact("new", revision=0)
    correction = fact("new", revision=1, value="120")
    for ordering in permutations([old, first, correction]):
        assert select_facts(ordering, FORMATION, TRADE) == (correction,)


def test_late_older_membership_event_does_not_undo_newer_effective_event() -> None:
    """Membership follows effective chronology once each announcement is known."""
    exit_row = event("exit", included=False, when=FORMATION - timedelta(days=1))
    late_join = MembershipEvent(
        security_id="SEC-A",
        event_id="late-join",
        included=True,
        effective_at=FORMATION - timedelta(days=2),
        available_at=FORMATION,
    )
    for ordering in permutations([exit_row, late_join]):
        assert select_universe(ordering, FORMATION, TRADE) == ()


def test_changed_membership_identity_is_rejected() -> None:
    """A reused announcement/security identity cannot silently change its effective time."""
    old = event("rebalance", when=FORMATION - timedelta(days=1))
    changed = event("rebalance")
    with pytest.raises(ResearchError, match="membership event has conflicting"):
        select_universe([changed, old], FORMATION, TRADE)
