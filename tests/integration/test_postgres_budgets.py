"""Actual transactions must commit one dispatch authorization across concurrent workers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.budgets import Operation
from factorforge.orchestration.postgres_budgets import reserve_operation, settle_operation
from factorforge.orchestration.postgres_runs import PostgresRunStore


def worker() -> Principal:
    """Only explicitly trusted worker identities have research execution authority."""
    return Principal("fixture", "owner", frozenset({"execute_research"}))


def operation() -> Operation:
    """A model call reserves the entire one-dollar fixture allowance."""
    return Operation(
        operation_id=uuid4(), kind="llm", request_sha256="a" * 64, max_cost_microusd=1000000
    )


def test_concurrent_reservation_authorizes_exactly_once(store: PostgresRunStore) -> None:
    """The row lock, not an in-process mutex, arbitrates competing connections."""
    run = store.create(
        ResearchBrief(idea="Original budget fixture", max_llm_cost_usd=Decimal("1")),
        "one",
        worker(),
    )
    request = operation()

    def reserve_one(_: int) -> bool:
        """Each worker opens a separate transaction against one canonical run."""
        return reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))[1]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve_one, range(8))) == 1
    ledger, allowed = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    assert not allowed and len(ledger.operations) == 1 and ledger.committed_microusd == 1000000
    with pytest.raises(ResearchError, match="budget"):
        reserve_operation(store, run.run_id, worker(), operation(), at=datetime.now(UTC))


@pytest.mark.parametrize(
    "other",
    [
        Principal("fixture", "owner", frozenset()),
        Principal("fixture", "other", frozenset({"execute_research"})),
    ],
)
def test_authorization_precedes_budget_mutation(store: PostgresRunStore, other: Principal) -> None:
    """Neither ownership alone nor another owner's capability authorizes this run."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    with pytest.raises(ResearchError) as error:
        reserve_operation(store, run.run_id, other, operation(), at=datetime.now(UTC))
    assert error.value.code in {"FORBIDDEN", "RUN_NOT_FOUND"}
    with store._connection() as connection:
        row = connection.execute("SELECT count(*) AS n FROM research_budgets").fetchone()
        assert row is not None and row["n"] == 0


def test_failed_commit_does_not_consume_dispatch(store: PostgresRunStore) -> None:
    """Failure after writing the ledger rolls back before the caller gets authorization."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()

    def crash(stage: str) -> None:
        """Inject the real transaction failure window just before commit."""
        if stage == "before_budget_commit":
            raise RuntimeError("original crash")

    store.failpoint = crash
    with pytest.raises(RuntimeError, match="original crash"):
        reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    store.failpoint = None
    assert reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))[1]


def test_restart_does_not_renew_dispatch_or_deadline(
    store: PostgresRunStore, database: tuple[str, str]
) -> None:
    """A new store instance reads the committed reservation after the original worker closes."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()
    ledger, _ = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    store.close()
    replacement = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
    try:
        late = ledger.deadline + timedelta(seconds=1)
        saved, allowed = reserve_operation(replacement, run.run_id, worker(), request, at=late)
        assert saved == ledger and not allowed
        with pytest.raises(ResearchError) as error:
            reserve_operation(replacement, run.run_id, worker(), operation(), at=late)
        assert error.value.code == "RESEARCH_BUDGET_REJECTED"
    finally:
        replacement.close()


@pytest.mark.parametrize("mutation", ["limits", "encoding", "request"])
def test_saved_budget_cannot_change_authoritative_limits(
    store: PostgresRunStore, mutation: str
) -> None:
    """Rehydration checks canonical identity and limits before replay grants any work."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()
    ledger, _ = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    if mutation == "limits":
        raw = ledger.model_copy(update={"max_operations": 127}).canonical_bytes().decode()
    elif mutation == "request":
        raw = ledger.model_copy(update={"request_sha256": "b" * 64}).canonical_bytes().decode()
    else:
        raw = " " + ledger.canonical_bytes().decode()
    with store._connection() as connection, connection.transaction():
        connection.execute(
            "UPDATE research_budgets SET ledger_json=%s WHERE run_id=%s", (raw, run.run_id)
        )
    with pytest.raises(ResearchError) as error:
        reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    assert error.value.code == "RESEARCH_BUDGET_CORRUPT"


class ResultStore:
    """Small in-memory original bytes isolate actual SQL settlement behavior."""

    def get(self, ref: ArtifactRef) -> bytes:
        """Return independent bytes to exercise the controller's identity verification."""
        return b"{}"

    def put(self, data: bytes, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        """These tests settle existing results and must never publish through this fixture."""
        raise AssertionError("unexpected publication")


@pytest.mark.parametrize("charge", [None, 500000, 2000000])
def test_settlement_preserves_actual_cost_and_exact_replay(
    store: PostgresRunStore, charge: int | None
) -> None:
    """Unknown and over-budget costs stay visible, including completion after the deadline."""
    import hashlib

    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()
    ledger, _ = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    reference = ArtifactRef(
        sha256=hashlib.sha256(b"{}").hexdigest(), size_bytes=2, media_type="application/json"
    )
    result_store: ArtifactStore = ResultStore()
    at = ledger.deadline + timedelta(seconds=1)
    observed = settle_operation(
        store,
        run.run_id,
        worker(),
        request.operation_id,
        result=reference,
        artifacts=result_store,
        actual_cost_microusd=charge,
        at=at,
    )
    assert observed.committed_microusd == (1000000 if charge is None else charge)
    assert observed.breached == (charge == 2000000)
    assert (
        settle_operation(
            store,
            run.run_id,
            worker(),
            request.operation_id,
            result=reference,
            artifacts=result_store,
            actual_cost_microusd=charge,
            at=at,
        )
        == observed
    )
    with pytest.raises(ResearchError):
        settle_operation(
            store,
            run.run_id,
            worker(),
            request.operation_id,
            result=reference,
            artifacts=result_store,
            actual_cost_microusd=0,
            at=at,
        )


def test_result_bytes_are_verified_before_settlement(store: PostgresRunStore) -> None:
    """A mismatched provider response leaves the original reservation unresolved."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()
    original, _ = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    wrong = ArtifactRef(sha256="a" * 64, size_bytes=2, media_type="application/json")
    with pytest.raises(ResearchError) as error:
        settle_operation(
            store,
            run.run_id,
            worker(),
            request.operation_id,
            result=wrong,
            artifacts=ResultStore(),
            actual_cost_microusd=0,
            at=datetime.now(UTC),
        )
    assert error.value.code == "RESEARCH_RESULT_INVALID"
    saved, allowed = reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))
    assert saved == original and not allowed


@pytest.mark.parametrize("case", ["owner", "unreserved", "oversized"])
def test_settlement_rejects_before_reading_artifacts(store: PostgresRunStore, case: str) -> None:
    """Authorization, reservation and byte limits precede provider access."""
    run = store.create(ResearchBrief(idea="Original budget fixture"), "one", worker())
    request = operation()
    reserve_operation(store, run.run_id, worker(), request, at=datetime.now(UTC))

    class NoRead(ResultStore):
        """Count provider access without relying on an exception that could be translated."""

        reads = 0

        def get(self, ref: ArtifactRef) -> bytes:
            """Any call proves a pre-read guard did not run."""
            self.reads += 1
            return b"{}"

    artifacts = NoRead()
    owner = worker() if case != "owner" else Principal("fixture", "other", worker().capabilities)
    identifier = uuid4() if case == "unreserved" else request.operation_id
    ref = ArtifactRef(
        sha256="a" * 64,
        size_bytes=2**20 + 1 if case == "oversized" else 2,
        media_type="application/json",
    )
    with pytest.raises(ResearchError):
        settle_operation(
            store,
            run.run_id,
            owner,
            identifier,
            result=ref,
            artifacts=artifacts,
            actual_cost_microusd=0,
            at=datetime.now(UTC),
        )
    assert artifacts.reads == 0
