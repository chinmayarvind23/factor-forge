"""Declared exchange sessions determine formation and later trade times without calendar guesses."""

import calendar as civil_calendar
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, ValidationError, field_validator, model_validator

from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest, Identifier, TimingSpec


def _utc(value: datetime) -> datetime:
    """Normalize instants while rejecting offsets that leave Python's supported year range."""
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ValueError("Calendar instant is outside the supported UTC range") from None


class TradingSession(Contract):
    """The initial UTC same-day session convention excludes overnight markets explicitly."""

    session_date: date
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @field_validator("opens_at", "closes_at")
    @classmethod
    def utc_clock(cls, value: datetime) -> datetime:
        """Equivalent offsets identify the same instant before calendar hashing or comparison."""
        return _utc(value)

    @model_validator(mode="after")
    def ordered_clocks(self) -> Self:
        """A close cannot precede its open or belong to a different declared UTC date."""
        if (
            self.opens_at >= self.closes_at
            or self.opens_at.date() != self.session_date
            or self.closes_at.date() != self.session_date
        ):
            raise ValueError("Session requires an earlier open and later close on its UTC date")
        return self


class SessionCalendar(Contract):
    """Coverage is an explicit source assertion; validation does not verify exchange holidays."""

    schema_version: Literal["session-calendar-v1"] = "session-calendar-v1"
    calendar_id: Identifier
    available_at: AwareDatetime
    coverage_start: date
    coverage_end: date
    sessions: Annotated[tuple[TradingSession, ...], Field(min_length=1, max_length=100000)]

    @field_validator("available_at")
    @classmethod
    def utc_publication(cls, value: datetime) -> datetime:
        """This clock asserts when the entire versioned schedule became available."""
        return _utc(value)

    @model_validator(mode="after")
    def ordered_inventory(self) -> Self:
        """Reject duplicate or unordered sessions rather than repairing the source calendar."""
        if self.coverage_start > self.coverage_end:
            raise ValueError("Calendar coverage must be ordered")
        previous: date | None = None
        for session in self.sessions:
            if not self.coverage_start <= session.session_date <= self.coverage_end or (
                previous is not None and session.session_date <= previous
            ):
                raise ValueError("Sessions must be unique, ordered and within declared coverage")
            previous = session.session_date
        return self


class FormationPlan(Contract):
    """Each deterministic decision retains its calendar identity and distinct information clocks."""

    calendar_sha256: Digest
    formation_at: AwareDatetime
    trade_at: AwareDatetime

    @field_validator("formation_at", "trade_at")
    @classmethod
    def utc_clock(cls, value: datetime) -> datetime:
        """Repeated wall-clock hours must compare as UTC instants, not local clock labels."""
        return _utc(value)

    @model_validator(mode="after")
    def causal_trade(self) -> Self:
        """Reloading a plan cannot turn it into a same-instant trade."""
        if self.formation_at >= self.trade_at:
            raise ValueError("Formation must precede trade")
        return self


def plan_formations(
    calendar: SessionCalendar, timing: TimingSpec, *, start: date, end: date
) -> tuple[FormationPlan, ...]:
    """Plan formation dates within an inclusive window, requiring complete source months.

    Trade times may fall after the formation window; an executor separately bounds its sample.
    Calendar coverage is asserted by the source, not inferred from the first and last row.
    """
    try:
        calendar = SessionCalendar.model_validate(calendar)
        timing = TimingSpec.model_validate(timing)
        if type(start) is not date or type(end) is not date or start > end:
            raise ValueError("Formation window requires ordered dates")
        raw = calendar.canonical_bytes()
        if (
            calendar.sha256 != timing.calendar.sha256
            or len(raw) != timing.calendar.size_bytes
            or calendar.calendar_id != timing.calendar_id
        ):
            raise ValueError("Timing does not bind this canonical calendar")
        first = start.replace(day=1)
        last = end.replace(day=civil_calendar.monthrange(end.year, end.month)[1])
        if calendar.coverage_start > first or calendar.coverage_end < last:
            raise ValueError("Formation months require complete declared calendar coverage")
    except (ValueError, ValidationError):
        raise ResearchError(
            "CALENDAR_INVALID", "Calendar or formation window is invalid.", 422
        ) from None

    last_sessions = {
        (session.session_date.year, session.session_date.month): index
        for index, session in enumerate(calendar.sessions)
    }
    plans = []
    for month_index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        year, zero_month = divmod(month_index, 12)
        month = zero_month + 1
        if timing.rebalance == "annual_june_last_session" and month != 6:
            continue
        index = last_sessions.get((year, month))
        if index is None:
            raise ResearchError("CALENDAR_INCOMPLETE", "A formation month has no sessions.", 422)
        formation = calendar.sessions[index]
        if not start <= formation.session_date <= end:
            continue
        if calendar.available_at > formation.closes_at:
            raise ResearchError(
                "CALENDAR_NOT_KNOWN", "Calendar version was unavailable at formation.", 422
            )
        trade_index = index + timing.trade_delay_sessions
        if trade_index >= len(calendar.sessions):
            raise ResearchError(
                "CALENDAR_INCOMPLETE", "Required later trade session is missing.", 422
            )
        plans.append(
            FormationPlan(
                calendar_sha256=timing.calendar.sha256,
                formation_at=formation.closes_at,
                trade_at=calendar.sessions[trade_index].opens_at,
            )
        )
    return tuple(plans)
