"""Source-only review controls real monthly dispatch and retains both model judgments."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.orchestration.command import OperatorRequest
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_experiments import (
    ExperimentPlan,
    ReviewedExperimentPlan,
    ReviewedResearchExperiments,
    research_experiments,
)
from factorforge.orchestration.research_report import build_report, render_report
from factorforge.orchestration.research_strategies import ResearchStrategies, _publish
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionReview
from infra.research.prepare_original import main as prepare_original


@pytest.mark.parametrize(
    "judgment", ["agree", "disagree", "uncertain", "invalid", "unavailable", "budget"]
)
def test_review_gates_dispatch_and_replays(
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
            """Use the source's intended direction independently of the review fixture."""
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
                        "long_short_direction": "long_high_short_low",
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
        """Exercise agreement, uncertainty and source-provenance rejection with retained output."""

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Return a separate judgment without editing the original extraction."""
            calls.append("review")
            return GenerationResult(
                status="unavailable" if judgment == "unavailable" else "success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=None
                if judgment == "unavailable"
                else json.dumps(
                    {
                        "direction": None
                        if judgment == "uncertain"
                        else (
                            "long_low_short_high"
                            if judgment == "disagree"
                            else "long_high_short_low"
                        ),
                        "quote": None
                        if judgment == "uncertain"
                        else (
                            "Invented quote"
                            if judgment == "invalid"
                            else "Go long the high-score bucket and short the low-score bucket"
                        ),
                        "pdf_page": None if judgment == "uncertain" else 1,
                        "uncertainty": "Direction unclear" if judgment == "uncertain" else None,
                    }
                ),
            )

    monkeypatch.setattr("factorforge.orchestration.extraction_worker.OllamaProvider", Extractor)
    monkeypatch.setattr(
        "factorforge.orchestration.direction_review_worker.OllamaProvider", Reviewer
    )
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    with TemporaryDirectory() as directory:
        request_path = Path(directory) / "request.json"
        object_path = Path(directory) / "objects"
        monkeypatch.setattr(
            "sys.argv", ["prepare", "--request", str(request_path), "--artifacts", str(object_path)]
        )
        prepare_original()
        request = OperatorRequest.model_validate_json(request_path.read_bytes())
        assert isinstance(request.plan, ExperimentPlan)
        plan = ReviewedExperimentPlan(
            execution=request.plan,
            max_cost_per_review_microusd=100000000 if judgment == "budget" else 1000000,
        )
        reviewed_request = OperatorRequest(brief=request.brief, plan=plan)
        assert (
            OperatorRequest.model_validate_json(reviewed_request.canonical_bytes())
            == reviewed_request
        )
        assert reviewed_request.sha256 != request.sha256
        run = store.create(request.brief, "one", owner)
        artifacts = LocalArtifactStore(object_path)
        actual = research_experiments(store, run.run_id, owner, plan, artifacts)
        assert isinstance(actual, ReviewedResearchExperiments)
        report = build_report(_publish(actual, artifacts), artifacts)
        assert len(report.candidates) == 1 and report.factor_promotion == "not_assessed"
        assert report.candidates[0].result == actual.execution.experiments[0].result
        assert "[Scheduler result](sha256/" in render_report(report)
        row = actual.execution.experiments[0]
        assert row.status == (
            "completed"
            if judgment == "agree"
            else "budget_stopped"
            if judgment == "budget"
            else "skipped"
        )
        assert (row.result is not None) == (judgment == "agree")
        if judgment == "budget":
            assert actual.reviews == () and calls == ["extract"]
        else:
            assert calls == ["extract", "review"]
            retained = actual.reviews[0]
            assert retained.agrees == (judgment == "agree")
            review = DirectionReview.model_validate_json(artifacts.get(retained.review))
            if judgment == "disagree":
                assert row.reason == "DIRECTION_REVIEW_DISAGREEMENT"
                assert review.observation is not None
                assert review.observation.direction == "long_low_short_high"
            strategies = ResearchStrategies.model_validate_json(
                artifacts.get(actual.execution.strategies)
            )
            extraction = strategies.sources.extractions[0].observation
            assert (
                extraction is not None and extraction.long_short_direction == "long_high_short_low"
            )
        budget = read_budget(store, run.run_id, owner)
        assert len(budget.operations) == (
            3 if judgment == "agree" else 1 if judgment == "budget" else 2
        )
        assert research_experiments(store, run.run_id, owner, plan, artifacts) == actual
        assert read_budget(store, run.run_id, owner) == budget
        assert len(calls) == (1 if judgment == "budget" else 2)
