"""Reservation examples freeze spending/retry semantics before expensive graph nodes exist."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.budgets import BudgetLedger, Observation, Operation, reserve, settle

NOW = datetime(2024, 1, 1, tzinfo=UTC)
RESULT = ArtifactRef(sha256="c" * 64, size_bytes=2, media_type="application/json")


def ledger(**changes: object) -> BudgetLedger:
    """A one-dollar ten-second original budget makes exact boundary examples inspectable."""
    return BudgetLedger.model_validate(
        dict(
            run_id=uuid4(),
            request_sha256="a" * 64,
            started_at=NOW,
            max_wall_seconds=10,
            max_cost_microusd=1_000_000,
            max_experiments=2,
            max_operations=128,
            operations=(),
        )
        | changes
    )


def operation(kind: str = "llm", cost: int = 600_000) -> Operation:
    """Bind one dispatch to immutable request bytes and a charge ceiling."""
    return Operation.model_validate(
        dict(operation_id=uuid4(), kind=kind, request_sha256="b" * 64, max_cost_microusd=cost)
    )


def test_cost_is_reserved_before_dispatch_and_known_settlement_releases_only_unused_money() -> None:
    """Two concurrent estimates cannot spend the same remaining money; attempts never refund."""
    first = operation()
    reserved, dispatch = reserve(ledger(), first, at=NOW)
    assert dispatch and reserved.committed_microusd == 600_000
    with pytest.raises(ResearchError, match="budget"):
        reserve(reserved, operation(), at=NOW)
    paid = settle(reserved, first.operation_id, actual_cost_microusd=200_000, result=RESULT, at=NOW)
    second, dispatch = reserve(paid, operation(cost=800_000), at=NOW)
    assert dispatch and second.committed_microusd == 1_000_000 and len(second.operations) == 2


def test_exact_retry_returns_receipt_without_authorizing_duplicate_dispatch() -> None:
    """Even expired or settled replays cannot reissue a previously allocated side effect."""
    request = operation()
    first, _ = reserve(ledger(), request, at=NOW)
    second, dispatch = reserve(first, request, at=NOW + timedelta(seconds=20))
    assert second == first and not dispatch
    with pytest.raises(ResearchError):
        reserve(first, request.model_copy(update={"max_cost_microusd": 1}), at=NOW)


def test_unknown_cost_keeps_reservation_and_result_reference() -> None:
    """Missing provider charge is not a free call and cannot release capacity."""
    request = operation()
    value, _ = reserve(ledger(), request, at=NOW)
    unknown = settle(value, request.operation_id, actual_cost_microusd=None, result=RESULT, at=NOW)
    assert unknown.committed_microusd == 600_000
    assert unknown.operations[0].observation is not None
    assert unknown.operations[0].observation.result == RESULT
    assert unknown.operations[0].observation.actual_cost_microusd is None
    assert (
        settle(unknown, request.operation_id, actual_cost_microusd=None, result=RESULT, at=NOW)
        == unknown
    )
    with pytest.raises(ResearchError):
        settle(unknown, request.operation_id, actual_cost_microusd=0, result=RESULT, at=NOW)


def test_actual_overrun_is_retained_and_blocks_further_work() -> None:
    """A low estimate cannot clamp a real charge or conceal breach even below the total ceiling."""
    request = operation(cost=100)
    value, _ = reserve(ledger(), request, at=NOW)
    value = settle(value, request.operation_id, actual_cost_microusd=101, result=RESULT, at=NOW)
    assert value.breached and value.committed_microusd == 101
    with pytest.raises(ResearchError):
        reserve(value, operation(cost=0), at=NOW)
    larger = operation(cost=1_000_000)
    value, _ = reserve(ledger(), larger, at=NOW)
    value = settle(
        value, larger.operation_id, actual_cost_microusd=2_000_000, result=RESULT, at=NOW
    )
    assert value.breached and value.committed_microusd == 2_000_000


@pytest.mark.parametrize(
    "at", [NOW - timedelta(microseconds=1), NOW + timedelta(seconds=10), datetime(2024, 1, 1)]
)
def test_invalid_or_expired_controller_clock_never_dispatches(at: datetime) -> None:
    """Deadline equality is exhausted; a naive or backward clock is not silently normalized."""
    with pytest.raises(ResearchError):
        reserve(ledger(), operation(), at=at)


def test_experiment_and_operation_limits_count_attempts_even_after_zero_cost_completion() -> None:
    """Free compute still consumes bounded work and cannot be retried indefinitely."""
    value = ledger(max_experiments=1)
    request = operation("experiment", 0)
    value, _ = reserve(value, request, at=NOW)
    value = settle(value, request.operation_id, actual_cost_microusd=0, result=RESULT, at=NOW)
    with pytest.raises(ResearchError):
        reserve(value, operation("experiment", 0), at=NOW)
    value = ledger(max_operations=1)
    value, _ = reserve(value, operation("validation", 0), at=NOW)
    with pytest.raises(ResearchError):
        reserve(value, operation("validation", 0), at=NOW)


@pytest.mark.parametrize("value", [True, 1.0, -1, 100_000_001])
def test_declared_money_requires_bounded_integer_millionths(value: object) -> None:
    """No Boolean or floating aliases enter the currency wire contract."""
    with pytest.raises(ValidationError):
        operation().model_copy(update={"max_cost_microusd": value}).canonical_bytes()


def test_non_llm_reservation_cannot_hide_an_llm_charge() -> None:
    """Compute operations have a distinct count budget and explicit zero LLM charge."""
    with pytest.raises(ValidationError):
        operation("experiment", 1)


def test_settlement_requires_existing_identity_and_ordered_clock() -> None:
    """Completion cannot allocate an unreserved call or backdate its observation."""
    value = ledger()
    with pytest.raises(ResearchError):
        settle(value, uuid4(), actual_cost_microusd=1, result=RESULT, at=NOW)
    request = operation()
    value, _ = reserve(value, request, at=NOW)
    with pytest.raises(ResearchError):
        settle(
            value,
            request.operation_id,
            actual_cost_microusd=1,
            result=RESULT,
            at=NOW - timedelta(seconds=1),
        )


def test_copied_ledger_cannot_bypass_budget_or_inventory_validation() -> None:
    """Reconstruction rejects forged limits, duplicate identities and oversubscribed costs."""
    value, _ = reserve(ledger(), operation(), at=NOW)
    for changed in [
        value.model_copy(update={"max_cost_microusd": 1}),
        value.model_copy(update={"operations": value.operations * 2}),
        value.model_copy(update={"max_operations": True}),
    ]:
        with pytest.raises(ResearchError):
            reserve(changed, operation(cost=0), at=NOW)
    assert BudgetLedger.model_validate_json(value.canonical_bytes()) == value


def test_reservation_cannot_rewind_clock_after_late_settlement() -> None:
    """Persisted observations provide a clock watermark across process restart."""
    request = operation(cost=1)
    value, _ = reserve(ledger(), request, at=NOW)
    value = settle(
        value,
        request.operation_id,
        actual_cost_microusd=0,
        result=RESULT,
        at=NOW + timedelta(seconds=11),
    )
    with pytest.raises(ResearchError):
        reserve(value, operation(cost=1), at=NOW + timedelta(seconds=1))


def test_unrepresentable_deadline_cannot_be_saved() -> None:
    """A valid start field cannot overflow the derived deadline at a later boundary."""
    with pytest.raises(ValidationError):
        ledger(started_at=datetime.max.replace(tzinfo=UTC))


def test_known_settlement_is_idempotent_and_after_deadline_is_recorded() -> None:
    """Result persistence may occur late without discarding actual billing evidence."""
    request = operation()
    value, _ = reserve(ledger(), request, at=NOW)
    at = NOW + timedelta(seconds=11)
    completed = settle(value, request.operation_id, actual_cost_microusd=12, result=RESULT, at=at)
    assert (
        settle(completed, request.operation_id, actual_cost_microusd=12, result=RESULT, at=at)
        == completed
    )
    assert reserve(completed, request, at=at) == (completed, False)


@pytest.mark.parametrize("cost", [True, 1.0, -1, 10**12 + 1])
def test_invalid_observation_cost_does_not_change_ledger(cost: object) -> None:
    """Observed billing remains bounded integer data and never enters arithmetic by coercion."""
    request = operation()
    value, _ = reserve(ledger(), request, at=NOW)
    with pytest.raises(ValidationError):
        Observation.model_validate(
            dict(actual_cost_microusd=cost, result=RESULT, at=NOW, sequence=0)
        )
    assert value.operations[0].observation is None


def test_settlement_finds_later_operation_and_keeps_other_reservations() -> None:
    """Responses attach to operation identity rather than positional completion order."""
    first, second = operation(cost=10), operation(cost=20)
    value, _ = reserve(ledger(), first, at=NOW)
    value, _ = reserve(value, second, at=NOW + timedelta(seconds=1))
    observed = settle(
        value,
        second.operation_id,
        actual_cost_microusd=2,
        result=RESULT,
        at=NOW + timedelta(seconds=2),
    )
    assert observed.operations[0] == value.operations[0]
    assert observed.committed_microusd == 12


@pytest.mark.parametrize("offset", [-1, 10])
def test_reloaded_history_rejects_reservations_outside_original_deadline(offset: int) -> None:
    """Saved metadata cannot backdate dispatch before start or extend the accepted deadline."""
    value, _ = reserve(ledger(), operation(), at=NOW)
    row = value.operations[0].model_copy(update={"reserved_at": NOW + timedelta(seconds=offset)})
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(value.model_copy(update={"operations": (row,)}))


def test_reloaded_reservation_cannot_spend_a_future_cost_refund() -> None:
    """A valid final balance does not prove capacity existed at each historic dispatch."""
    first, second = operation(), operation()
    value, _ = reserve(ledger(), first, at=NOW)
    value = settle(
        value,
        first.operation_id,
        actual_cost_microusd=0,
        result=RESULT,
        at=NOW + timedelta(seconds=9),
    )
    value, _ = reserve(value, second, at=NOW + timedelta(seconds=9))
    backdated = value.operations[1].model_copy(update={"reserved_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(
            value.model_copy(update={"operations": (value.operations[0], backdated)})
        )


def test_same_instant_observed_overrun_keeps_previously_reserved_work() -> None:
    """Equal timestamp precision cannot move a later overrun before an earlier valid dispatch."""
    first, second = operation(cost=600_000), operation(cost=400_000)
    value, _ = reserve(ledger(), first, at=NOW)
    value, _ = reserve(value, second, at=NOW)
    value = settle(value, first.operation_id, actual_cost_microusd=700_000, result=RESULT, at=NOW)
    assert value.breached and value.committed_microusd == 1_100_000


@pytest.mark.parametrize("mutation", ["gap", "duplicate", "reordered"])
def test_event_inventory_requires_complete_unique_order(mutation: str) -> None:
    """Dropping or reordering events cannot change capacity available to dispatch."""
    value, _ = reserve(ledger(), operation(cost=1), at=NOW)
    value, _ = reserve(value, operation(cost=1), at=NOW)
    first, second = value.operations
    if mutation == "reordered":
        rows = (second, first)
    else:
        rows = (first, second.model_copy(update={"sequence": 2 if mutation == "gap" else 0}))
    with pytest.raises(ValidationError):
        BudgetLedger.model_validate(value.model_copy(update={"operations": rows}))
