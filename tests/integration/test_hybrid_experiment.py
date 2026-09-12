"""Real PostgreSQL hybrids reuse settled accounting and preserve held compositions."""

import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_monthly_worker import request as monthly_request
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRun
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.hybrid_fixture import prepare_hybrid_fixture
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.research_brief import ResearchBrief
from factorforge.domain.targets import Rational
from factorforge.factors.hybrid import HybridComponent, HybridRequest
from factorforge.orchestration.hybrid_command import HybridExperimentRequest, execute_hybrid
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore


@pytest.mark.parametrize("compatible", [True, False])
def test_hybrid_executes_or_holds_then_replays(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch, compatible: bool
) -> None:
    """The composite consumes one experiment operation; a held proposal consumes none."""
    owner = Principal("fixture", "hybrid-owner", frozenset({"execute_research"}))
    brief = ResearchBrief(idea="Blend two original direction-aligned signals", max_experiments=1)
    run = store.create(brief, "hybrid", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        original = monthly_request(artifacts)
        proposed = prepare_hybrid_fixture(Path(__file__).resolve().parents[2], artifacts)
        wire = proposed.components[1].strategy.model_dump(mode="json")
        if not compatible:
            wire["costs"]["commission_bps"] += 1
        second = RawStrategySpec.model_validate_json(json.dumps(wire))
        request = HybridExperimentRequest(
            brief=brief,
            hybrid=HybridRequest(
                name="Original blend",
                rationale=brief.idea,
                components=tuple(
                    HybridComponent(strategy=parent, weight=Rational.from_fraction(weight))
                    for parent, weight in zip(
                        (proposed.components[0].strategy, second),
                        (Fraction(3, 4), Fraction(1, 4)),
                        strict=True,
                    )
                ),
            ),
            initial_cash_usd=original.initial_cash_usd,
            evaluated_at=original.evaluated_at,
        )
        result = execute_hybrid(store, run.run_id, owner, request, artifacts)
        assert result.status == ("completed" if compatible else "held")
        if compatible:
            assert result.experiment is not None
            executed = MonthlyRun.model_validate_json(artifacts.get(result.experiment))
            assert executed.performance is not None
            assert str(executed.performance.terminal_nav_usd) == "1057.98"
            assert {row.fact.source_id for row in executed.formations[0].assembly.selections} == {
                "score-A",
                "score-B",
                "quality-A",
                "quality-B",
            }
        else:
            assert result.experiment is None
        before = read_budget(store, run.run_id, owner)
        assert len(before.operations) == int(compatible)

        def no_repeat(*args: object, **kwargs: object) -> None:
            """Repeated hybrid publication must recover the existing monthly result."""
            raise AssertionError("duplicate hybrid accounting")

        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        assert execute_hybrid(store, run.run_id, owner, request, artifacts) == result
        assert read_budget(store, run.run_id, owner) == before
