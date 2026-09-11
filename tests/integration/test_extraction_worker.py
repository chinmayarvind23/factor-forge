"""Budgeted extraction retains one provider observation across PostgreSQL worker restarts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.extraction_worker import (
    ExtractionCommand,
    execute_extraction_operation,
)
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.extraction import SourcePacket, SourcePage


@pytest.mark.parametrize("delivered", [True, False])
def test_extraction_delivery_is_recorded_once(
    store: PostgresRunStore,
    database: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    delivered: bool,
) -> None:
    """Controlled provider outcomes exercise retention without claiming model accuracy."""
    calls = []

    class Provider:
        """Original deterministic provider output isolates durable dispatch behavior."""

        def __init__(self, *, deadline: float) -> None:
            """Require the worker to propagate an explicit finite execution allowance."""
            assert deadline > 0

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Retain an explicit provider record for the extraction's evidence closure."""
            calls.append(request)
            return GenerationResult(
                status="success" if delivered else "unavailable",
                content=json.dumps(
                    {
                        "status": "extracted",
                        "refusal_reason": None,
                        "refusal_category": None,
                        "formula": "sales",
                        "required_inputs": ["sales"],
                        "long_short_direction": None,
                        "bucket_count": None,
                        "weighting": None,
                        "lookback_months": None,
                        "holding_months": None,
                        "rebalance_frequency": None,
                        "formation_lag_months": None,
                        "formation_rule": None,
                        "source_pages": [1],
                    }
                )
                if delivered
                else None,
                record=artifacts.put(b"{}", media_type="application/json"),
            )

    monkeypatch.setattr("factorforge.orchestration.extraction_worker.OllamaProvider", Provider)
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original source extraction"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        page = artifacts.put(
            b"An original example describes ranking stocks by sales.", media_type="text/plain"
        )
        command = ExtractionCommand(
            source=SourcePacket(
                paper_id="original",
                source_sha256="a" * 64,
                selected_strategy="original sales ranking",
                pages=(SourcePage(pdf_page=1, artifact=page),),
            ),
            max_cost_microusd=1000000,
        )
        result = execute_extraction_operation(store, run.run_id, owner, command, artifacts)
        assert (
            result.status == ("extracted" if delivered else "provider_failed") and len(calls) == 1
        )
        budget = read_budget(store, run.run_id, owner)
        assert budget.committed_microusd == 1000000
        assert budget.operations[0].observation is not None
        assert budget.operations[0].observation.actual_cost_microusd is None
        store.close()
        replacement = PostgresRunStore(database[0], schema=database[1], require_test_database=True)
        try:
            assert (
                execute_extraction_operation(replacement, run.run_id, owner, command, artifacts)
                == result
            )
            assert len(calls) == 1
        finally:
            replacement.close()
