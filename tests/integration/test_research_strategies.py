"""Actual PostgreSQL source workers feed retained, executable strategy drafts."""

import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_monthly_worker import request as monthly_request
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRequest
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import PaperDocument
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.monthly_worker import execute_monthly_operation
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_strategies import (
    ReviewedStrategyBinding,
    research_strategies,
)
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry


@pytest.mark.parametrize("outcome", ["compiled", "unbound", "needs_review", "source_unavailable"])
def test_source_drafts_publish_and_replay(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """A controlled extraction becomes a draft with retained source evidence and one model call."""
    calls = []

    class Provider:
        """Original observations exercise orchestration without a source-accuracy claim."""

        def __init__(self, *, deadline: float) -> None:
            """Require the durable worker's run deadline."""
            assert deadline > 0

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Retain the controlled response as provider evidence."""
            calls.append(request)
            return GenerationResult(
                status="unavailable" if outcome == "source_unavailable" else "success",
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
                        "holding_months": 12 if outcome == "needs_review" else 1,
                        "rebalance_frequency": "monthly",
                        "formation_lag_months": 0,
                        "formation_rule": "Last session close each month",
                        "source_pages": [1],
                    }
                ),
            )

    monkeypatch.setattr("factorforge.orchestration.extraction_worker.OllamaProvider", Provider)
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="original score"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        command = monthly_request(artifacts)
        source = SourcePacket(
            paper_id="original",
            source_sha256="a" * 64,
            selected_strategy="original score",
            pages=(
                SourcePage(
                    pdf_page=1,
                    artifact=artifacts.put(b"Original score strategy", media_type="text/plain"),
                ),
            ),
        )
        catalog = LiteratureCatalog(
            entries=(
                LiteratureEntry(
                    source=source,
                    document=PaperDocument(
                        paper_id="original",
                        title="original score",
                        text="original score",
                        source_url="https://example.org/original",
                        source_sha256="a" * 64,
                        content_kind="original_summary",
                        source_version="v1",
                    ),
                ),
            )
        )
        bindings = (
            (
                ReviewedStrategyBinding(
                    source=source,
                    environment=command.spec,
                    reviewed_formation_rule="Last session close each month",
                ),
            )
            if outcome != "unbound"
            else ()
        )
        result = research_strategies(
            store,
            run.run_id,
            owner,
            catalog,
            bindings,
            artifacts,
            max_cost_per_source_microusd=1000000,
        )
        candidate = result.candidates[0]
        assert candidate.status == outcome
        if outcome in {"compiled", "needs_review"}:
            assert candidate.draft is not None and candidate.artifact is not None
            assert artifacts.get(candidate.artifact) == candidate.draft.canonical_bytes()
        if outcome == "compiled":
            assert candidate.draft is not None and candidate.draft.strategy is not None
            assert result.sources.extractions[0].record in candidate.draft.strategy.source_refs
            experiment = MonthlyRequest.model_validate(
                command.model_copy(update={"spec": candidate.draft.strategy})
            )
            executed = execute_monthly_operation(store, run.run_id, owner, experiment, artifacts)
            assert executed.status == "completed" and executed.performance is not None
            assert executed.performance.terminal_nav_usd == Decimal("1057.98")
            assert (
                execute_monthly_operation(store, run.run_id, owner, experiment, artifacts)
                == executed
            )
        assert (
            research_strategies(
                store,
                run.run_id,
                owner,
                catalog,
                bindings,
                artifacts,
                max_cost_per_source_microusd=1000000,
            )
            == result
        )
        assert len(calls) == 1
        assert len(read_budget(store, run.run_id, owner).operations) == (
            2 if outcome == "compiled" else 1
        )
        if bindings:
            changed = bindings[0].model_copy(
                update={
                    "source": source.model_copy(update={"selected_strategy": "another strategy"})
                }
            )
            with pytest.raises(ResearchError) as error:
                research_strategies(
                    store,
                    run.run_id,
                    owner,
                    catalog,
                    (changed,),
                    artifacts,
                    max_cost_per_source_microusd=1000000,
                )
            assert error.value.code == "STRATEGY_BINDING_INVALID" and len(calls) == 1
