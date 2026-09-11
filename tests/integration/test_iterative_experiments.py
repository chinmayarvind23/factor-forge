"""Source-only review controls real monthly dispatch and retains both model judgments."""

import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRun
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.factors.direction_amendment import DirectionAmendment
from factorforge.orchestration.command import OperatorRequest
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_experiments import (
    IterativeExperimentPlan,
    IterativeResearchExperiments,
    research_experiments,
)
from factorforge.orchestration.research_strategies import ResearchStrategies
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from infra.research.prepare_original import main as prepare_original


@pytest.mark.parametrize(
    "judgment", ["confirmed", "uncertain", "opposite", "budget", "crash", "agree"]
)
def test_one_revision_amends_or_holds_and_replays(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch, judgment: str
) -> None:
    """Only a supported matching direction can spend an experiment slot; replay spends neither."""
    calls = []

    class Extractor:
        """Retain a controlled complete observation for the original monthly strategy."""

        def __init__(self, *, deadline: float) -> None:
            """Require the original deadline at each model boundary."""
            assert deadline > 0

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Use a reversed extraction except when testing the no-revision path."""
            calls.append("extract")
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "status": "extracted",
                        "refusal_reason": None,
                        "refusal_category": None,
                        "formula": "score",
                        "required_inputs": ["score"],
                        "long_short_direction": "long_high_short_low"
                        if judgment == "agree"
                        else "long_low_short_high",
                        "bucket_count": 2,
                        "weighting": "equal_weight",
                        "lookback_months": None,
                        "holding_months": 1,
                        "rebalance_frequency": "monthly",
                        "formation_lag_months": 0,
                        "formation_rule": "Last session close each month",
                        "source_pages": [1],
                    }
                ),
            )

    class Reviewer(Extractor):
        """An exact source quote supports the original fixture direction."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Retain the second judgment separately from the extraction."""
            calls.append("review")
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "direction": "long_high_short_low",
                        "quote": "Go long the high-score bucket and short the low-score bucket",
                        "pdf_page": 1,
                        "uncertainty": None,
                    }
                ),
            )

    class Reviser(Extractor):
        """The third reading may confirm review, remain uncertain or retain the first choice."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Freeze the new model observation without silently replacing the prior two."""
            calls.append("revision")
            assert "conflicting_observations" in json.loads(request.user)
            return GenerationResult(
                status="success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "direction": None
                        if judgment == "uncertain"
                        else "long_low_short_high"
                        if judgment == "opposite"
                        else "long_high_short_low",
                        "quote": None
                        if judgment == "uncertain"
                        else "Go long the high-score bucket and short the low-score bucket",
                        "pdf_page": None if judgment == "uncertain" else 1,
                        "uncertainty": "Unclear direction" if judgment == "uncertain" else None,
                    }
                ),
            )

    monkeypatch.setattr("factorforge.orchestration.extraction_worker.OllamaProvider", Extractor)
    monkeypatch.setattr(
        "factorforge.orchestration.direction_review_worker.OllamaProvider", Reviewer
    )
    monkeypatch.setattr(
        "factorforge.orchestration.direction_revision_worker.OllamaProvider", Reviser
    )
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    with TemporaryDirectory() as directory:
        request_path = Path(directory) / "request.json"
        object_path = Path(directory) / "objects"
        monkeypatch.setattr(
            "sys.argv",
            [
                "prepare",
                "--request",
                str(request_path),
                "--artifacts",
                str(object_path),
                "--direction-revision",
            ],
        )
        prepare_original()
        request = OperatorRequest.model_validate_json(request_path.read_bytes())
        assert isinstance(request.plan, IterativeExperimentPlan)
        plan = request.plan
        if judgment == "budget":
            plan = plan.model_copy(update={"max_cost_per_revision_microusd": 100000000})
        run = store.create(request.brief, "one", owner)
        artifacts = LocalArtifactStore(object_path)
        if judgment == "crash":

            def crash(stage: str) -> None:
                """Stop after amended execution settles but before graph publication."""
                if stage == "before_monthly_manifest":
                    raise RuntimeError("amended publication crash")

            store.failpoint = crash
            with pytest.raises(RuntimeError, match="amended publication crash"):
                research_experiments(store, run.run_id, owner, plan, artifacts)
            store.failpoint = None

            def no_repeat(*args: object, **kwargs: object) -> None:
                """The settled amended experiment cannot execute again on graph recovery."""
                raise AssertionError("duplicate amended execution")

            monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        actual = research_experiments(store, run.run_id, owner, plan, artifacts)
        assert isinstance(actual, IterativeResearchExperiments)
        row = actual.execution.experiments[0]
        completed = judgment in {"confirmed", "crash", "agree"}
        assert row.status == (
            "completed" if completed else "budget_stopped" if judgment == "budget" else "skipped"
        )
        if completed:
            assert row.result is not None
            monthly = MonthlyRun.model_validate_json(artifacts.get(row.result))
            assert monthly.performance is not None
            assert monthly.performance.terminal_nav_usd == Decimal("1057.98")
        else:
            assert row.result is None
        strategies = ResearchStrategies.model_validate_json(
            artifacts.get(actual.execution.strategies)
        )
        original = strategies.candidates[0].draft
        assert original is not None
        assert original.request.observation.long_short_direction == (
            "long_high_short_low" if judgment == "agree" else "long_low_short_high"
        )
        if judgment in {"agree", "budget"}:
            assert actual.amendments == ()
            assert calls == ["extract", "review"]
        else:
            assert calls == ["extract", "review", "revision"]
            amendment = DirectionAmendment.model_validate_json(
                artifacts.get(actual.amendments[0].amendment)
            )
            assert amendment.request.original == original
            if completed:
                assert amendment.draft is not None and amendment.draft.strategy is not None
                assert (
                    amendment.draft.request.observation.long_short_direction
                    == "long_high_short_low"
                )
                assert row.result is not None
                monthly = MonthlyRun.model_validate_json(artifacts.get(row.result))
                assert monthly.request.spec == amendment.draft.strategy
            else:
                assert amendment.draft is None
        budget = read_budget(store, run.run_id, owner)
        expected_operations = (
            3 if judgment == "agree" else 4 if completed else 2 if judgment == "budget" else 3
        )
        assert len(budget.operations) == expected_operations
        assert research_experiments(store, run.run_id, owner, plan, artifacts) == actual
        assert read_budget(store, run.run_id, owner) == budget
        assert len(calls) == (2 if judgment in {"agree", "budget"} else 3)
