"""Formation uses declared sessions and complete months, never business-day guesses."""

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.calendar import (
    FormationPlan,
    SessionCalendar,
    TradingSession,
    plan_formations,
)
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import TimingSpec


def calendar() -> SessionCalendar:
    """A small authored calendar deliberately includes a weekend and a later-session gap."""
    return SessionCalendar.model_validate(
        {
            "calendar_id": "authored-calendar-v1",
            "available_at": datetime(2024, 3, 1, tzinfo=UTC),
            "coverage_start": date(2024, 4, 1),
            "coverage_end": date(2024, 7, 31),
            "sessions": tuple(
                {
                    "session_date": date.fromisoformat(day),
                    "opens_at": datetime.fromisoformat(day + "T13:30:00+00:00"),
                    "closes_at": datetime.fromisoformat(day + "T20:00:00+00:00"),
                }
                for day in (
                    "2024-04-29",
                    "2024-04-30",
                    "2024-05-04",
                    "2024-05-31",
                    "2024-06-28",
                    "2024-07-01",
                )
            ),
        }
    )


class FallBackZone(tzinfo):
    """A repeated local hour exposes wall-clock comparisons without host tzdata dependence."""

    def utcoffset(self, value: datetime | None) -> timedelta:
        """The later repeated hour uses the winter offset."""
        return timedelta(hours=-5 if value is not None and value.fold else -4)

    def dst(self, value: datetime | None) -> timedelta:
        """Explicit offset behavior is sufficient for this original contract probe."""
        return timedelta(0)

    def tzname(self, value: datetime | None) -> str:
        """The synthetic name carries no exchange or geographic-calendar claim."""
        return "AuthoredFold"


def test_repeated_local_hours_cannot_reverse_causal_order() -> None:
    """UTC normalization rejects a later clock label that is actually an earlier instant."""
    zone = FallBackZone()
    with pytest.raises(ValidationError):
        FormationPlan(
            calendar_sha256="a" * 64,
            formation_at=datetime(2024, 11, 3, 1, 15, tzinfo=zone, fold=1),
            trade_at=datetime(2024, 11, 3, 1, 45, tzinfo=zone, fold=0),
        )


@pytest.mark.parametrize("model", ["session", "calendar", "plan"])
def test_utc_range_overflow_is_a_validation_failure(model: str) -> None:
    """Out-of-range normalized instants cannot leak an untyped arithmetic exception."""
    instant = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14)))
    with pytest.raises(ValidationError):
        if model == "session":
            TradingSession(session_date=date(1, 1, 1), opens_at=instant, closes_at=instant)
        elif model == "calendar":
            SessionCalendar.model_validate(calendar().model_dump() | {"available_at": instant})
        else:
            FormationPlan(calendar_sha256="a" * 64, formation_at=instant, trade_at=instant)


def test_equivalent_plan_offsets_preserve_canonical_identity() -> None:
    """Serialization identifies instants independently of the provider's offset spelling."""
    plan = FormationPlan(
        calendar_sha256="a" * 64,
        formation_at=datetime(2024, 4, 30, 20, tzinfo=UTC),
        trade_at=datetime(2024, 5, 1, 13, 30, tzinfo=UTC),
    )
    shifted = FormationPlan.model_validate(
        plan.model_dump()
        | {
            "formation_at": plan.formation_at.astimezone(timezone(timedelta(hours=5))),
            "trade_at": plan.trade_at.astimezone(timezone(timedelta(hours=-4))),
        }
    )
    assert shifted.sha256 == plan.sha256


def timing(value: SessionCalendar, **changes: object) -> TimingSpec:
    """Bind calendar bytes to the same required timing contract used by FactorSpec."""
    return TimingSpec.model_validate(
        {
            "calendar": ArtifactRef(
                sha256=value.sha256,
                size_bytes=len(value.canonical_bytes()),
                media_type="application/json",
            ),
            "calendar_id": value.calendar_id,
            "timezone": "UTC",
            "formation": "session_close",
            "trade": "subsequent_session_open",
            "trade_delay_sessions": 1,
            "rebalance": "monthly_last_session",
            "lookback_months": None,
            "formation_lag_months": 0,
            "holding_months": 1,
            "vintage_allocation": "nonoverlapping",
            "within_cohort": "buy_and_hold",
        }
        | changes
    )


def test_formations_follow_supplied_sessions_instead_of_weekday_assumptions() -> None:
    """The supplied exchange calendar, including authored gaps, determines the later open."""
    value = calendar()
    plans = plan_formations(value, timing(value), start=date(2024, 4, 1), end=date(2024, 6, 30))
    assert [plan.formation_at.date().isoformat() for plan in plans] == [
        "2024-04-30",
        "2024-05-31",
        "2024-06-28",
    ]
    assert [plan.trade_at.date().isoformat() for plan in plans] == [
        "2024-05-04",
        "2024-06-28",
        "2024-07-01",
    ]
    assert all(
        plan.calendar_sha256 == value.sha256 and plan.formation_at < plan.trade_at for plan in plans
    )


def test_annual_june_formation_uses_last_declared_june_session() -> None:
    """Annual timing does not turn the latest available non-June session into a June formation."""
    value = calendar()
    rule = timing(value, rebalance="annual_june_last_session", holding_months=12)
    plans = plan_formations(value, rule, start=date(2024, 4, 1), end=date(2024, 6, 30))
    assert len(plans) == 1 and plans[0].formation_at.date() == date(2024, 6, 28)


def test_delay_counts_sessions_and_missing_later_session_fails() -> None:
    """A session delay counts supplied opens; unavailable execution time is never extrapolated."""
    value = calendar()
    rule = timing(value, trade_delay_sessions=2)
    plans = plan_formations(value, rule, start=date(2024, 4, 1), end=date(2024, 4, 30))
    assert plans[0].trade_at.date() == date(2024, 5, 31)
    with pytest.raises(ResearchError, match="later trade session"):
        plan_formations(value, rule, start=date(2024, 6, 1), end=date(2024, 6, 30))


@pytest.mark.parametrize(
    "case",
    [
        "unordered",
        "duplicate",
        "reversed",
        "naive",
        "wrong_day",
        "outside",
        "empty",
        "coverage_order",
    ],
)
def test_invalid_calendar_structure_is_rejected(case: str) -> None:
    """Session order, time zones and source coverage are input invariants, not repair requests."""
    payload = calendar().model_dump()
    sessions = list(payload["sessions"])
    if case == "unordered":
        sessions.reverse()
    elif case == "duplicate":
        sessions.append(sessions[-1])
    elif case == "reversed":
        sessions[0]["opens_at"] = sessions[0]["closes_at"]
    elif case == "naive":
        sessions[0]["opens_at"] = datetime(2024, 4, 29, 13, 30)
    elif case == "wrong_day":
        sessions[0]["opens_at"] -= timedelta(days=1)
    elif case == "outside":
        payload["coverage_start"] = date(2024, 5, 1)
    elif case == "empty":
        sessions = []
    else:
        payload["coverage_start"] = date(2025, 1, 1)
    payload["sessions"] = tuple(sessions)
    with pytest.raises(ValidationError):
        SessionCalendar.model_validate(payload)


@pytest.mark.parametrize("case", ["start", "end", "missing_month"])
def test_incomplete_formation_months_fail_instead_of_using_partial_last_sessions(case: str) -> None:
    """A truncated month cannot make an earlier session look like the true final session."""
    payload = calendar().model_dump()
    if case == "start":
        payload["coverage_start"] = date(2024, 4, 15)
    elif case == "end":
        payload["coverage_end"] = date(2024, 7, 15)
    else:
        payload["sessions"] = tuple(
            row for row in payload["sessions"] if row["session_date"].month != 5
        )
    value = SessionCalendar.model_validate(payload)
    with pytest.raises(ResearchError):
        plan_formations(value, timing(value), start=date(2024, 4, 20), end=date(2024, 7, 10))


@pytest.mark.parametrize(
    "case", ["hash", "size", "name", "copied_calendar", "copied_timing", "date_order", "datetime"]
)
def test_planning_revalidates_boundaries_before_returning_trade_times(case: str) -> None:
    """Forged nested models or mismatched source identity cannot yield a trusted plan."""
    value = calendar()
    rule = timing(value)
    start, end = date(2024, 4, 1), date(2024, 4, 30)
    if case == "hash":
        rule = rule.model_copy(
            update={"calendar": rule.calendar.model_copy(update={"sha256": "a" * 64})}
        )
    elif case == "size":
        rule = rule.model_copy(
            update={"calendar": rule.calendar.model_copy(update={"size_bytes": 1})}
        )
    elif case == "name":
        rule = rule.model_copy(update={"calendar_id": "different"})
    elif case == "copied_calendar":
        value = value.model_copy(update={"sessions": ()})
    elif case == "copied_timing":
        rule = rule.model_copy(update={"trade_delay_sessions": 0})
    elif case == "date_order":
        start, end = end, start
    else:
        start = datetime(2024, 4, 1, tzinfo=UTC)
    with pytest.raises(ResearchError):
        plan_formations(value, rule, start=start, end=end)


@pytest.mark.parametrize("seconds_after", [0, 1])
def test_calendar_version_must_be_known_at_every_formation(seconds_after: int) -> None:
    """Retrospective schedule changes cannot silently move a historical month-end decision."""
    value = SessionCalendar.model_validate(
        calendar().model_dump()
        | {"available_at": datetime(2024, 4, 30, 20, tzinfo=UTC) + timedelta(seconds=seconds_after)}
    )
    if seconds_after:
        with pytest.raises(ResearchError) as failure:
            plan_formations(value, timing(value), start=date(2024, 4, 1), end=date(2024, 4, 30))
        assert failure.value.code == "CALENDAR_NOT_KNOWN"
    else:
        assert (
            len(
                plan_formations(value, timing(value), start=date(2024, 4, 1), end=date(2024, 4, 30))
            )
            == 1
        )


def test_partial_request_excludes_month_end_and_annual_non_june_is_empty() -> None:
    """Complete supplied months may legitimately have no formation inside a narrower request."""
    value = calendar()
    assert (
        plan_formations(value, timing(value), start=date(2024, 4, 1), end=date(2024, 4, 29)) == ()
    )
    assert (
        plan_formations(
            value,
            timing(value, rebalance="annual_june_last_session", holding_months=12),
            start=date(2024, 4, 1),
            end=date(2024, 5, 31),
        )
        == ()
    )
