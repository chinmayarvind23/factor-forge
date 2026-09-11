"""Independent budget probes reject histories that borrow capacity from future settlements."""

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from uuid import UUID

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.budgets import BudgetLedger, Observation, Operation, reserve, settle

NOW = datetime(2024, 11, 3, 5, tzinfo=UTC)
RESULT = ArtifactRef(sha256="d" * 64, size_bytes=2, media_type="application/json")


def original() -> BudgetLedger:
    """A one-dollar original ledger makes unavailable future credits unambiguous."""
    return BudgetLedger(
        run_id=UUID(int=501),
        request_sha256="a" * 64,
        started_at=NOW,
        max_wall_seconds=7200,
        max_cost_microusd=1_000_000,
        max_experiments=2,
        max_operations=128,
        operations=(),
    )


def request(identity: int, cost: int = 600_000) -> Operation:
    """Independent operation identities bind the same ordinary request with explicit ceilings."""
    return Operation(
        operation_id=UUID(int=identity), kind="llm", request_sha256="b" * 64, max_cost_microusd=cost
    )


def test_saved_history_cannot_release_later_credit_before_its_observation() -> None:
    """Final committed totals cannot prove that an earlier dispatch had available funds."""
    first, second = request(1), request(2)
    value, _ = reserve(original(), first, at=NOW)
    paid = settle(
        value,
        first.operation_id,
        actual_cost_microusd=0,
        result=RESULT,
        at=NOW + timedelta(seconds=9),
    )
    legal, _ = reserve(paid, second, at=NOW + timedelta(seconds=9))
    forged = legal.operations[1].model_copy(update={"reserved_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(
            legal.model_copy(update={"operations": (legal.operations[0], forged)})
        )


def test_saved_history_cannot_dispatch_after_previously_observed_breach() -> None:
    """A retained overrun permits already admitted work, never later authorizations."""
    first, second = request(1, 10), request(2, 10)
    value, _ = reserve(original(), first, at=NOW)
    value, _ = reserve(value, second, at=NOW + timedelta(seconds=1))
    legal = settle(
        value,
        first.operation_id,
        actual_cost_microusd=11,
        result=RESULT,
        at=NOW + timedelta(seconds=2),
    )
    observation = legal.operations[0].observation
    assert observation is not None
    forged = legal.operations[0].model_copy(
        update={"observation": observation.model_copy(update={"at": NOW})}
    )
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(
            legal.model_copy(update={"operations": (forged, legal.operations[1])})
        )


def test_equivalent_observation_offsets_have_one_canonical_identity() -> None:
    """Saved replay identity must not depend on an equivalent displayed timezone offset."""
    first = Observation(actual_cost_microusd=1, result=RESULT, at=NOW, sequence=1)
    other = Observation(
        actual_cost_microusd=1,
        result=RESULT,
        at=NOW.astimezone(timezone(timedelta(hours=5))),
        sequence=1,
    )
    assert first.canonical_bytes() == other.canonical_bytes()


@pytest.mark.parametrize("role", ["start", "observation"])
def test_unrepresentable_utc_clocks_are_schema_failures(role: str) -> None:
    """Offset-aware input outside representable UTC cannot escape as raw arithmetic overflow."""
    at = datetime.min.replace(tzinfo=timezone(timedelta(hours=14)))
    with pytest.raises(ValidationError):
        if role == "start":
            BudgetLedger.model_validate(original().model_copy(update={"started_at": at}))
        else:
            Observation(actual_cost_microusd=1, result=RESULT, at=at, sequence=1)


class FoldClock(tzinfo):
    """Original repeated-hour clock avoids a host-dependent timezone database requirement."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        """The repeated hour moves from minus four to minus five hours."""
        return timedelta(hours=-5 if dt is not None and dt.fold else -4)

    def dst(self, dt: datetime | None) -> timedelta:
        """The offset itself carries the fold for this bounded original clock."""
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        """A stable label completes the synthetic clock without external timezone data."""
        return "original-fold-clock"


def test_fold_order_uses_absolute_instant_in_reloaded_rows() -> None:
    """A later second-fold observation may have an earlier local wall-clock spelling."""
    zone = FoldClock()
    first = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=0)
    later = datetime(2024, 11, 3, 1, 15, tzinfo=zone, fold=1)
    operation = request(1)
    value, _ = reserve(original(), operation, at=first)
    legal = settle(value, operation.operation_id, actual_cost_microusd=1, result=RESULT, at=later)
    observation = legal.operations[0].observation
    assert observation is not None
    row = legal.operations[0].model_copy(
        update={"reserved_at": first, "observation": observation.model_copy(update={"at": later})}
    )
    restored = BudgetLedger.model_validate(legal.model_copy(update={"operations": (row,)}))
    assert restored.canonical_bytes() == legal.canonical_bytes()


def test_same_clock_sequence_cannot_spend_a_not_yet_observed_refund() -> None:
    """Sequence must establish capacity even when every event has the same valid timestamp."""
    first, second = request(1), request(2)
    value, _ = reserve(original(), first, at=NOW)
    value = settle(value, first.operation_id, actual_cost_microusd=0, result=RESULT, at=NOW)
    value, _ = reserve(value, second, at=NOW)
    observation = value.operations[0].observation
    assert observation is not None
    rows = (
        value.operations[0].model_copy(
            update={"observation": observation.model_copy(update={"sequence": 2})}
        ),
        value.operations[1].model_copy(update={"sequence": 1}),
    )
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(value.model_copy(update={"operations": rows}))


def test_last_allowed_settlement_preserves_all_256_events() -> None:
    """The operation cap must leave room to observe every already reserved operation."""
    value = original()
    operations = [request(1000 + i, 0) for i in range(128)]
    for operation in operations:
        value, dispatch = reserve(value, operation, at=NOW)
        assert dispatch
    for operation in reversed(operations):
        value = settle(value, operation.operation_id, actual_cost_microusd=0, result=RESULT, at=NOW)
    assert value.next_sequence == 256
    assert value.operations[0].observation is not None
    assert value.operations[0].observation.sequence == 255
    assert BudgetLedger.model_validate_json(value.canonical_bytes()) == value
    assert reserve(value, operations[0], at=NOW) == (value, False)
    with pytest.raises(ResearchError):
        reserve(value, request(9999, 0), at=NOW)
