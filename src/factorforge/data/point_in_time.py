"""Select only information known by formation, preserving historical revisions and membership."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from factorforge.domain.errors import ResearchError

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class FundamentalFact(BaseModel):
    """One context-qualified concept in exact units; a source is a document, not a row ID.

    ``period_start=None`` denotes an instant fact. Duration facts retain their start
    to keep quarterly and annual observations distinct. Providers must qualify any
    dimensional context in ``concept`` and assign a new revision for corrections.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    security_id: Identifier
    concept: Identifier
    period_end: date
    period_start: date | None = None
    value: Decimal
    unit: Identifier
    available_at: AwareDatetime
    source_id: Identifier
    revision: Annotated[int, Field(strict=True, ge=0)] = 0

    @field_validator("available_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        """Normalize equivalent offsets before immutable metadata is serialized."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def historical_period(self) -> "FundamentalFact":
        """This contract describes reported facts, not forecasts of a future accounting period."""
        if self.period_end > self.available_at.date():
            raise ValueError("A reported period cannot end after its availability timestamp.")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("A reported duration must start on or before its end.")
        return self


class MembershipEvent(BaseModel):
    """One security's event in a supplied universe; announcement IDs may span securities."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    security_id: Identifier
    event_id: Identifier
    included: Annotated[bool, Field(strict=True)]
    effective_at: AwareDatetime
    available_at: AwareDatetime

    @field_validator("available_at", "effective_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        """Event ordering uses absolute time regardless of the provider's original offset."""
        return value.astimezone(UTC)


def validate_decision_time(formation_at: datetime, trade_at: datetime) -> None:
    """Equal availability is allowed, but trading must occur strictly after formation."""
    if (
        formation_at.utcoffset() is None
        or trade_at.utcoffset() is None
        or formation_at.astimezone(UTC) >= trade_at.astimezone(UTC)
    ):
        raise ResearchError(
            "TIMING_INVALID", "Require aware formation time before trade time.", 422
        )


type FactKey = tuple[str, str, str, date, str]


def _fact_key(row: FundamentalFact) -> FactKey:
    """Preserve period and units; an empty start sorts instant facts without date sentinels."""
    start = row.period_start.isoformat() if row.period_start is not None else ""
    return row.security_id, row.concept, start, row.period_end, row.unit


def select_facts(
    records: Iterable[FundamentalFact],
    formation_at: datetime,
    trade_at: datetime,
) -> tuple[FundamentalFact, ...]:
    """Select by publication then revision per fact identity, without unit conversion.

    Validate all eligible history before selecting so ingestion order cannot hide a
    conflict. Equal values use the smallest source ID as representative provenance;
    callers must retain the complete input manifest for all corroborating sources.
    """
    validate_decision_time(formation_at, trade_at)
    formation_at = formation_at.astimezone(UTC)
    selected: dict[FactKey, FundamentalFact] = {}
    sources: dict[tuple[FactKey, str, int], FundamentalFact] = {}
    versions: dict[tuple[FactKey, datetime, int], FundamentalFact] = {}
    for row in records:
        if row.available_at > formation_at:
            continue
        key = _fact_key(row)
        source_key = (key, row.source_id, row.revision)
        if source_key in sources and sources[source_key] != row:
            raise ResearchError("DATA_CONFLICT", "A source identity has conflicting values.", 422)
        sources[source_key] = row
        version_key = (key, row.available_at, row.revision)
        previous = versions.get(version_key)
        if previous is not None and previous.value != row.value:
            raise ResearchError("DATA_CONFLICT", "Resolve conflicting contemporaneous facts.", 422)
        if previous is None or row.source_id < previous.source_id:
            versions[version_key] = row
    for (key, _, _), row in versions.items():
        current = selected.get(key)
        rank = (row.available_at, row.revision)
        if current is None or rank > (current.available_at, current.revision):
            selected[key] = row
    return tuple(selected[key] for key in sorted(selected))


def select_universe(
    records: Iterable[MembershipEvent],
    formation_at: datetime,
    trade_at: datetime,
) -> tuple[str, ...]:
    """Historical membership follows stable IDs and only events known and effective at formation."""
    validate_decision_time(formation_at, trade_at)
    formation_at = formation_at.astimezone(UTC)
    selected: dict[str, MembershipEvent] = {}
    events: dict[tuple[str, str], MembershipEvent] = {}
    versions: dict[tuple[str, datetime, datetime], MembershipEvent] = {}
    for row in records:
        if row.available_at > formation_at or row.effective_at > formation_at:
            continue
        event_key = (row.security_id, row.event_id)
        if event_key in events and events[event_key] != row:
            raise ResearchError("DATA_CONFLICT", "A membership event has conflicting values.", 422)
        events[event_key] = row
        version_key = (row.security_id, row.effective_at, row.available_at)
        previous = versions.get(version_key)
        if previous is not None and previous.included != row.included:
            raise ResearchError("DATA_CONFLICT", "Resolve conflicting membership events.", 422)
        versions[version_key] = row
    for row in versions.values():
        current = selected.get(row.security_id)
        rank = (row.effective_at, row.available_at)
        if current is None or rank > (current.effective_at, current.available_at):
            selected[row.security_id] = row
    return tuple(sorted(key for key, row in selected.items() if row.included))
