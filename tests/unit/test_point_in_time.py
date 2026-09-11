"""Hand-selected observations establish the information boundary before factor accounting."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from factorforge.data.point_in_time import (
    FundamentalFact,
    MembershipEvent,
    select_facts,
    select_universe,
)
from factorforge.domain.errors import ResearchError

FORMATION = datetime(2024, 5, 1, 20, tzinfo=UTC)
TRADE = FORMATION + timedelta(hours=17, minutes=30)


def fact(source: str, available: datetime, value: str, revision: int = 0) -> FundamentalFact:
    """The economic period stays fixed while publication and correction time change."""
    return FundamentalFact(
        security_id="SEC-A",
        concept="assets",
        period_end=date(2023, 12, 31),
        value=Decimal(value),
        unit="USD",
        available_at=available,
        source_id=source,
        revision=revision,
    )


def test_later_filing_and_restatement_do_not_rewrite_history() -> None:
    """Historical formation keeps the original filing until its correction is available."""
    original = fact("filing-1", FORMATION, "100")
    correction = fact("filing-2", FORMATION + timedelta(days=3), "140", 1)
    assert select_facts([correction, original], FORMATION, TRADE) == (original,)
    later = FORMATION + timedelta(days=4)
    assert select_facts([original, correction], later, later + timedelta(hours=1)) == (correction,)


@given(st.permutations([0, 1, 2]))
def test_selection_is_independent_of_row_order(order: list[int]) -> None:
    """Ingestion order cannot choose a different historical accounting value."""
    rows = [
        fact("original", FORMATION - timedelta(days=5), "90"),
        fact("known-correction", FORMATION - timedelta(days=1), "100", 1),
        fact("future-correction", FORMATION + timedelta(days=1), "999", 2),
    ]
    assert select_facts([rows[i] for i in order], FORMATION, TRADE) == (rows[1],)


def test_conflicting_same_publication_is_not_arbitrarily_selected() -> None:
    """Two incompatible claims at the same revision/time require ingestion resolution."""
    with pytest.raises(ResearchError) as error:
        select_facts([fact("a", FORMATION, "100"), fact("b", FORMATION, "200")], FORMATION, TRADE)
    assert error.value.code == "DATA_CONFLICT"


def test_invalid_timing_is_rejected() -> None:
    """Same-time execution and timezone-free input cannot masquerade as causal trading."""
    row = fact("a", FORMATION, "100")
    for formation, trade in [
        (FORMATION, FORMATION),
        (TRADE, FORMATION),
        (FORMATION.replace(tzinfo=None), TRADE),
    ]:
        with pytest.raises(ResearchError):
            select_facts([row], formation, trade)
    with pytest.raises(ValidationError):
        fact("naive", FORMATION.replace(tzinfo=None), "100")
    with pytest.raises(ValidationError):
        fact("nonfinite", FORMATION, "NaN")


def test_membership_uses_known_events_and_stable_security_identity() -> None:
    """An exit announcement in the future cannot erase prior known membership."""
    old = MembershipEvent(
        security_id="SEC-A",
        event_id="join",
        included=True,
        effective_at=FORMATION - timedelta(days=10),
        available_at=FORMATION - timedelta(days=10),
    )
    exit_event = MembershipEvent(
        security_id="SEC-A",
        event_id="exit",
        included=False,
        effective_at=FORMATION - timedelta(days=1),
        available_at=FORMATION + timedelta(days=1),
    )
    future_join = MembershipEvent(
        security_id="SEC-B",
        event_id="future",
        included=True,
        effective_at=FORMATION + timedelta(days=2),
        available_at=FORMATION - timedelta(days=1),
    )
    assert select_universe([exit_event, future_join, old], FORMATION, TRADE) == ("SEC-A",)
    later = FORMATION + timedelta(days=3)
    assert select_universe([old, future_join, exit_event], later, later + timedelta(hours=1)) == (
        "SEC-B",
    )
