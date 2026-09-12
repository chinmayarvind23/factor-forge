"""Actual PostgreSQL graph execution feeds longer-sample validation and identical replay."""

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
from factorforge.data.validation_fixture import prepare_validation_fixture
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.monthly_graph import MonthlyExperimentGraph
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.validation.research import ValidationRequest, validate_research


def test_longer_execution_and_validation_replay(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three measured test blocks reuse one settled experiment with no accounting redispatch."""
    owner = Principal("fixture", "validation-owner", frozenset({"execute_research"}))
    run = store.create(
        ResearchBrief(idea="Validate original longer path", max_experiments=1), "validation", owner
    )
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        spec = prepare_validation_fixture(Path(__file__).resolve().parents[2], artifacts)
        command = MonthlyRequest(
            spec=spec,
            initial_cash_usd=Decimal("1002"),
            evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        )
        root = MonthlyExperimentGraph(store, run.run_id, owner, command, artifacts).finish()
        request = ValidationRequest(
            result=root, initial_train_size=3, test_size=3, hac_lags=1, embargo_seconds=86400
        )
        result = validate_research(request, artifacts)
        assert len(result.folds) == 3
        assert all(fold.test_diagnostic is not None for fold in result.folds)
        before = read_budget(store, run.run_id, owner)
        assert len(before.operations) == 1

        def no_dispatch(*args: object, **kwargs: object) -> None:
            """A repeated graph finish must recover the settled accounting operation."""
            raise AssertionError("duplicate accounting")

        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_dispatch)
        assert MonthlyExperimentGraph(store, run.run_id, owner, command, artifacts).finish() == root
        assert validate_research(request, artifacts) == result
        assert read_budget(store, run.run_id, owner) == before
