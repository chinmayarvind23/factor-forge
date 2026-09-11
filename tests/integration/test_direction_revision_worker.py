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
from factorforge.domain.extraction import SourceExtraction
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.direction_revision_worker import (
    DirectionRevisionCommand,
    execute_direction_revision_operation,
)
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import DirectionObservation, DirectionReview
from factorforge.retrieval.direction_revision import DirectionRevisionRequest
from factorforge.retrieval.extraction import ExtractionResult, SourcePacket, SourcePage


@pytest.mark.parametrize("outcome", ["supported", "provider_failed", "reserved", "delivered"])
def test_revision_restart_and_crash_boundaries(
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
        "factorforge.orchestration.direction_revision_worker.OllamaProvider", Provider
    )
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original direction review"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        page = artifacts.put(quote.encode(), media_type="text/plain")
        source = SourcePacket(
            paper_id="original",
            source_sha256=page.sha256,
            selected_strategy="score ranking",
            pages=(SourcePage(pdf_page=1, artifact=page),),
        )
        initial_observation = SourceExtraction(
            status="extracted",
            refusal_reason=None,
            refusal_category=None,
            formula="score",
            required_inputs=["score"],
            long_short_direction="long_low_short_high",
            bucket_count=2,
            weighting="equal_weight",
            lookback_months=None,
            holding_months=1,
            rebalance_frequency="monthly",
            formation_lag_months=0,
            formation_rule="Last session close each month",
            source_pages=[1],
        )
        command = DirectionRevisionCommand(
            request=DirectionRevisionRequest(
                source=source,
                extraction=ExtractionResult(
                    status="extracted",
                    observation=initial_observation,
                    record=artifacts.put(
                        b'{"attempt":"extraction"}', media_type="application/json"
                    ),
                ),
                review=DirectionReview(
                    status="supported",
                    observation=DirectionObservation(
                        direction="long_high_short_low", quote=quote, pdf_page=1, uncertainty=None
                    ),
                    record=artifacts.put(b'{"attempt":"review"}', media_type="application/json"),
                ),
            ),
            max_cost_microusd=1000000,
        )

        def crash(stage: str) -> None:
            """Inject process loss immediately after reservation or before result settlement."""
            if (outcome == "reserved" and stage == "after_direction_revision_reservation") or (
                outcome == "delivered" and stage == "before_direction_revision_settlement"
            ):
                raise RuntimeError("original crash")

        store.failpoint = crash
        result = None
        if outcome in {"reserved", "delivered"}:
            with pytest.raises(RuntimeError, match="original crash"):
                execute_direction_revision_operation(store, run.run_id, owner, command, artifacts)
        else:
            result = execute_direction_revision_operation(
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
                    execute_direction_revision_operation(
                        replacement, run.run_id, owner, command, artifacts
                    )
                assert error.value.code == "RESEARCH_OPERATION_UNRESOLVED"
            else:
                assert (
                    execute_direction_revision_operation(
                        replacement, run.run_id, owner, command, artifacts
                    )
                    == result
                )
            assert len(calls) == calls_before
            assert read_budget(replacement, run.run_id, owner) == budget
        finally:
            replacement.close()
