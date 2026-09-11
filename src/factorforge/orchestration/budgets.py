"""Pure reservation transitions precede dispatch; persistence and authority belong to the worker."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, ValidationError, field_validator, model_validator

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Digest

MicroUSD = Annotated[int, Field(ge=0, le=100_000_000)]
EventSequence = Annotated[int, Field(ge=0, le=255)]


def _utc(at: datetime) -> datetime:
    """A trusted aware wall clock is required; active work also needs its own monotonic deadline."""
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise ValueError("Budget clock must be aware")
    try:
        return at.astimezone(UTC)
    except OverflowError:
        raise ValueError("Budget clock exceeds the UTC range") from None


class TimedContract(Contract):
    """Normalize every event clock before ordering, including repeated DST wall times."""

    @field_validator("*")
    @classmethod
    def normalize_clock(cls, value: object) -> object:
        """Equivalent aware instants produce one canonical UTC identity."""
        return _utc(value) if isinstance(value, datetime) else value


class Operation(Contract):
    """One dispatch identity binds immutable request bytes and a worst-case LLM charge."""

    operation_id: UUID
    kind: Literal["llm", "experiment", "validation"]
    request_sha256: Digest
    max_cost_microusd: MicroUSD

    @model_validator(mode="after")
    def distinct_cost(self) -> Self:
        """Compute counts cannot masquerade as permission for a hidden model charge."""
        if self.kind != "llm" and self.max_cost_microusd != 0:
            raise ValueError("Only LLM operations reserve LLM cost")
        return self


class Observation(TimedContract):
    """Unknown charge holds its reservation; measured overruns remain visible without clamping."""

    actual_cost_microusd: Annotated[int, Field(ge=0, le=10**12)] | None
    result: ArtifactRef
    at: AwareDatetime
    sequence: EventSequence


class Reservation(TimedContract):
    """Attempt history is immutable even when measured cost releases unused dollars."""

    operation: Operation
    reserved_at: AwareDatetime
    sequence: EventSequence
    observation: Observation | None = None

    @model_validator(mode="after")
    def ordered_observation(self) -> Self:
        """An observed completion cannot precede the reservation that authorized dispatch."""
        if self.observation is not None and (
            self.observation.at < self.reserved_at or self.observation.sequence <= self.sequence
        ):
            raise ValueError("Observation precedes reservation")
        return self

    @property
    def committed_microusd(self) -> int:
        """Only a known charge can reduce reserved capacity; pending and unknown costs stay held."""
        if self.observation is None or self.observation.actual_cost_microusd is None:
            return self.operation.max_cost_microusd
        return self.observation.actual_cost_microusd

    @property
    def overrun(self) -> bool:
        """An individual estimate breach remains a breach even if the total budget has room."""
        return self.committed_microusd > self.operation.max_cost_microusd


class BudgetLedger(TimedContract):
    """Bounded serial-worker budget state has no authority to execute or mutate durable storage."""

    schema_version: Literal["research-budget-v1"] = "research-budget-v1"
    run_id: UUID
    request_sha256: Digest
    started_at: AwareDatetime
    max_wall_seconds: Annotated[int, Field(ge=1, le=86400)]
    max_cost_microusd: Annotated[MicroUSD, Field(gt=0)]
    max_experiments: Annotated[int, Field(ge=1, le=100)]
    max_operations: Annotated[int, Field(ge=1, le=128)]
    operations: Annotated[tuple[Reservation, ...], Field(max_length=128)]

    @model_validator(mode="after")
    def coherent_history(self) -> Self:
        """Rehydrated state cannot contain duplicate dispatches or unfunded pending reservations."""
        try:
            deadline = self.deadline
        except OverflowError:
            raise ValueError("Budget deadline exceeds the supported clock") from None
        if len(self.operations) > self.max_operations or len(
            {row.operation.operation_id for row in self.operations}
        ) != len(self.operations):
            raise ValueError("Operation inventory exceeds its budget or repeats identity")
        if (
            sum(row.operation.kind == "experiment" for row in self.operations)
            > self.max_experiments
        ):
            raise ValueError("Experiment inventory exceeds its budget")
        _validate_history(self, deadline)
        return self

    @property
    def deadline(self) -> datetime:
        """Restart does not renew the original wall-time allowance."""
        return self.started_at + timedelta(seconds=self.max_wall_seconds)

    @property
    def committed_microusd(self) -> int:
        """Exact integer addition avoids per-call rounding loss across the bounded history."""
        return sum(row.committed_microusd for row in self.operations)

    @property
    def breached(self) -> bool:
        """Known overruns prevent future work without erasing the offending observation."""
        return any(row.overrun for row in self.operations)

    @property
    def clock_watermark(self) -> datetime:
        """A restart or backward wall-clock adjustment cannot revive earlier dispatch time."""
        return max(
            [self.started_at]
            + [row.reserved_at for row in self.operations]
            + [row.observation.at for row in self.operations if row.observation is not None]
        )

    @property
    def next_sequence(self) -> int:
        """Contiguous event ordinals disambiguate events sharing the same clock precision."""
        return len(self.operations) + sum(row.observation is not None for row in self.operations)


def _validate_history(ledger: BudgetLedger, deadline: datetime) -> None:
    """Replay capacity at each dispatch so later refunds cannot fund an earlier operation."""
    events = [(row.sequence, row.reserved_at, row, False) for row in ledger.operations]
    events += [
        (row.observation.sequence, row.observation.at, row, True)
        for row in ledger.operations
        if row.observation is not None
    ]
    events.sort(key=lambda event: event[0])
    if [event[0] for event in events] != list(range(len(events))):
        raise ValueError("Event sequence is not a contiguous unique history")
    sequences = [row.sequence for row in ledger.operations]
    if sequences != sorted(sequences):
        raise ValueError("Reservations must retain dispatch order")
    committed, breached, previous = 0, False, ledger.started_at
    for _, at, row, is_observation in events:
        if at < previous:
            raise ValueError("Event clock moved backward")
        previous = at
        if is_observation:
            committed += row.committed_microusd - row.operation.max_cost_microusd
            breached = breached or row.overrun
        else:
            committed += row.operation.max_cost_microusd
            if breached or at >= deadline or committed > ledger.max_cost_microusd:
                raise ValueError("Historical dispatch exceeded its budget")


def _failure() -> ResearchError:
    """Keep immutable request and billing contents out of safe public failure messages."""
    return ResearchError(
        "RESEARCH_BUDGET_REJECTED", "The research budget cannot authorize this operation.", 409
    )


def reserve(
    ledger: BudgetLedger, operation: Operation, *, at: datetime
) -> tuple[BudgetLedger, bool]:
    """Return new state and one-time dispatch permission; commit atomically before side effects.

    Callers must resolve owner/run/request identity and serialize concurrent mutations. A pure
    returned Boolean cannot supply that authority. Replays always return false, including
    unresolved prior work; no automatic retry of a potentially billed/executed call is safe.
    """
    try:
        ledger, operation, at = (
            BudgetLedger.model_validate(ledger),
            Operation.model_validate(operation),
            _utc(at),
        )
        for row in ledger.operations:
            if row.operation.operation_id == operation.operation_id:
                if row.operation != operation:
                    raise ValueError("Operation identity conflict")
                return ledger, False
        if ledger.breached or at >= ledger.deadline or at < ledger.clock_watermark:
            raise ValueError("Budget is breached or expired")
        if ledger.committed_microusd + operation.max_cost_microusd > ledger.max_cost_microusd:
            raise ValueError("Cost capacity is exhausted")
        return BudgetLedger.model_validate(
            ledger.model_copy(
                update={
                    "operations": (
                        *ledger.operations,
                        Reservation(
                            operation=operation, reserved_at=at, sequence=ledger.next_sequence
                        ),
                    ),
                }
            )
        ), True
    except (ValueError, TypeError, OverflowError, ValidationError):
        raise _failure() from None


def settle(
    ledger: BudgetLedger,
    operation_id: UUID,
    *,
    actual_cost_microusd: int | None,
    result: ArtifactRef,
    at: datetime,
) -> BudgetLedger:
    """Retain one controller-supplied observation after work; unknown charge is never inferred zero.

    Result byte verification and provider billing provenance are caller obligations. Observations
    are append-once: a later reconciliation needs a separately versioned protocol, not overwrite.
    Late completion remains recordable after the deadline and actual overruns are not discarded.
    """
    try:
        ledger = BudgetLedger.model_validate(ledger)
        for index, row in enumerate(ledger.operations):
            if row.operation.operation_id != operation_id:
                continue
            observation = Observation(
                actual_cost_microusd=actual_cost_microusd,
                result=result,
                at=_utc(at),
                sequence=row.observation.sequence
                if row.observation is not None
                else ledger.next_sequence,
            )
            if row.observation is not None:
                if row.observation != observation:
                    raise ValueError("Settlement conflicts with existing observation")
                return ledger
            updated = Reservation.model_validate(
                row.model_copy(update={"observation": observation})
            )
            return BudgetLedger.model_validate(
                ledger.model_copy(
                    update={
                        "operations": (
                            *ledger.operations[:index],
                            updated,
                            *ledger.operations[index + 1 :],
                        ),
                    }
                )
            )
        raise ValueError("Unreserved settlement")
    except (ValueError, TypeError, OverflowError, ValidationError):
        raise _failure() from None
