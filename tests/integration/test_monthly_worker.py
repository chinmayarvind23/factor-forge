"""A real monthly executor and PostgreSQL ledger share one durable operation identity."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRequest
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.monthly_worker import execute_monthly_operation
from factorforge.orchestration.postgres_runs import PostgresRunStore


def request(artifacts: LocalArtifactStore) -> MonthlyRequest:
    """Load only the frozen original inputs; expected outputs are never supplied to execution."""
    root = Path(__file__).resolve().parents[2] / "data/backtests/monthly-raw-v1"
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        artifacts.put(
            (root / "inputs" / f"{name}.json").read_bytes(), media_type="application/json"
        )
    return MonthlyRequest(
        spec=RawStrategySpec.model_validate_json((root / "strategy.json").read_bytes()),
        initial_cash_usd=Decimal("1002"),
        evaluated_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("cash", ["1002", "1000"])
def test_real_execution_settles_and_restart_reuses_result(
    store: PostgresRunStore, database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, cash: str
) -> None:
    """Reopening the database recovers the exact stored result without rerunning the engine."""
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original monthly worker fixture"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        command = MonthlyRequest.model_validate(
            request(artifacts).model_copy(update={"initial_cash_usd": Decimal(cash)})
        )
        actual = execute_monthly_operation(store, run.run_id, owner, command, artifacts)
        if cash == "1002":
            assert actual.status == "completed" and actual.path is not None
            assert actual.path.closes[-1].nav_usd == Decimal("1057.98")
        else:
            assert actual.status == "failed" and actual.failure_code == "FUNDING_QUANTITY_PRECISION"
            assert actual.path is None
        store.close()
        replacement = PostgresRunStore(database[0], schema=database[1], require_test_database=True)

        def no_repeat(*args: object, **kwargs: object) -> None:
            """A replay must use retained evidence rather than call the monthly executor."""
            raise AssertionError("duplicate execution")

        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        try:
            assert (
                execute_monthly_operation(replacement, run.run_id, owner, command, artifacts)
                == actual
            )
        finally:
            replacement.close()


def test_crash_after_reservation_does_not_redispatch(store: PostgresRunStore) -> None:
    """A committed reservation remains unresolved when the first worker stops before execution."""
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original monthly worker fixture"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        command = request(artifacts)

        def crash(stage: str) -> None:
            """Exercise the actual gap between budget commit and backend execution."""
            if stage == "after_monthly_reservation":
                raise RuntimeError("original crash")

        store.failpoint = crash
        with pytest.raises(RuntimeError, match="original crash"):
            execute_monthly_operation(store, run.run_id, owner, command, artifacts)
        store.failpoint = None
        with pytest.raises(ResearchError) as error:
            execute_monthly_operation(store, run.run_id, owner, command, artifacts)
        assert error.value.code == "RESEARCH_OPERATION_UNRESOLVED"
