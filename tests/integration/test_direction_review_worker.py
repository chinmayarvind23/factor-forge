"""Actual PostgreSQL reservations preserve review outcomes and prevent ambiguous retries."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.direction_review_worker import (
    DirectionReviewCommand,
    execute_direction_review_operation,
)
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.extraction import SourcePacket, SourcePage


@pytest.mark.parametrize("outcome", ["supported", "provider_failed", "reserved", "delivered"])
def test_review_restart_and_crash_boundaries(
    store: PostgresRunStore,
    database: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """Reopen real storage after delivery or either crash window without a second model call."""
    calls = []
    quote = "Buy high scores and sell low scores."

    class Provider:
        """Controlled observations isolate worker lifecycle from extraction accuracy."""

        def __init__(self, *, deadline: float) -> None:
            """Require the original run's explicit time allowance."""
            assert deadline > 0

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Keep a provider receipt for every dispatched review."""
            calls.append(request)
            return GenerationResult(
                status="unavailable" if outcome == "provider_failed" else "success",
                content=None
                if outcome == "provider_failed"
                else json.dumps(
                    {
                        "direction": "long_high_short_low",
                        "quote": quote,
                        "pdf_page": 1,
                        "uncertainty": None,
                    }
                ),
                record=artifacts.put(b"{}", media_type="application/json"),
            )

    monkeypatch.setattr(
        "factorforge.orchestration.direction_review_worker.OllamaProvider", Provider
    )
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original direction review"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        page = artifacts.put(quote.encode(), media_type="text/plain")
        command = DirectionReviewCommand(
            source=SourcePacket(
                paper_id="original",
                source_sha256=page.sha256,
                selected_strategy="score ranking",
                pages=(SourcePage(pdf_page=1, artifact=page),),
            ),
            max_cost_microusd=1000000,
        )

        def crash(stage: str) -> None:
            """Inject process loss immediately after reservation or before result settlement."""
            if (outcome == "reserved" and stage == "after_direction_review_reservation") or (
                outcome == "delivered" and stage == "before_direction_review_settlement"
            ):
                raise RuntimeError("original crash")

        store.failpoint = crash
        result = None
        if outcome in {"reserved", "delivered"}:
            with pytest.raises(RuntimeError, match="original crash"):
                execute_direction_review_operation(store, run.run_id, owner, command, artifacts)
        else:
            result = execute_direction_review_operation(
                store, run.run_id, owner, command, artifacts
            )
            assert result.status == outcome
        budget = read_budget(store, run.run_id, owner)
        assert len(budget.operations) == 1
        if result is not None:
            assert budget.committed_microusd == 1000000
            observation = budget.operations[0].observation
            assert observation is not None and observation.actual_cost_microusd is None
        calls_before = len(calls)
        assert calls_before == (0 if outcome == "reserved" else 1)
        store.close()
        replacement = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
        try:
            if result is None:
                with pytest.raises(ResearchError) as error:
                    execute_direction_review_operation(
                        replacement, run.run_id, owner, command, artifacts
                    )
                assert error.value.code == "RESEARCH_OPERATION_UNRESOLVED"
            else:
                assert (
                    execute_direction_review_operation(
                        replacement, run.run_id, owner, command, artifacts
                    )
                    == result
                )
            assert len(calls) == calls_before
            assert read_budget(replacement, run.run_id, owner) == budget
        finally:
            replacement.close()
