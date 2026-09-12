"""Real PostgreSQL carries controlled source extraction through synthesis and hybrid replay."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.data.synthesis_fixture import prepare_synthesis_fixture
from factorforge.domain.errors import ResearchError
from factorforge.evaluation.synthesis import grade_synthesis
from factorforge.factors.hybrid import publish
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.synthesis_command import (
    QwenSynthesisResearchRequest,
    execute_synthesis_research,
)
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.direction_review import REVIEW_PROMPT
from factorforge.retrieval.extraction import SYSTEM_PROMPT
from factorforge.retrieval.synthesis import SYNTHESIS_PROMPT


@pytest.mark.parametrize("outcome", ["completed", "abstained", "uncertain_review", "pending"])
@pytest.mark.parametrize("qwen_extraction", [False, True])
def test_full_synthesis_path_reuses_all_operations(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch, outcome: str, qwen_extraction: bool
) -> None:
    """Five controlled model calls produce one hybrid; held cases remain fully inspectable."""
    calls = []

    def generate(
        self: object, request: GenerationRequest, artifacts: ArtifactStore
    ) -> GenerationResult:
        """Dispatch by actual frozen task prompt, retaining all real request payloads."""
        calls.append(request)
        payload = json.loads(request.user)
        wire: dict[str, Any]
        if request.system == SYSTEM_PROMPT:
            assert request.model == ("qwen3:8b" if qwen_extraction else "llama3.1:8b")
            name = "quality" if "quality" in payload["selected_strategy"] else "score"
            wire = dict(
                status="extracted",
                refusal_reason=None,
                refusal_category=None,
                formula=name,
                required_inputs=[name],
                long_short_direction="long_high_short_low",
                bucket_count=2,
                weighting="equal_weight",
                lookback_months=None,
                holding_months=1,
                rebalance_frequency="monthly",
                formation_lag_months=0,
                formation_rule="Last session close each month",
                source_pages=[1],
            )
        elif request.system == REVIEW_PROMPT:
            assert request.model == "llama3.1:8b"
            wire = dict(
                direction="long_high_short_low",
                quote=payload["pages"][0]["text"],
                pdf_page=1,
                uncertainty=None,
            )
            if outcome == "uncertain_review":
                wire = dict(
                    direction=None,
                    quote=None,
                    pdf_page=None,
                    uncertainty="Controlled uncertain review",
                )
        else:
            assert request.system == SYNTHESIS_PROMPT
            wire = dict(
                status="proposed",
                rationale="Combine distinct original hypotheses at the requested weights.",
                abstention=None,
                allocations=[
                    dict(
                        paper_id=row["paper_id"],
                        numerator=3 if row["paper_id"].endswith("score") else 1,
                        denominator=4,
                        quote=row["pages"][0]["text"],
                        pdf_page=1,
                    )
                    for row in payload["candidates"]
                ],
            )
            if outcome == "abstained":
                wire.update(status="abstained", allocations=[], abstention="Controlled abstention")
        return GenerationResult(
            status="success",
            content=json.dumps(wire),
            record=artifacts.put(b"{}", media_type="application/json"),
        )

    monkeypatch.setattr("factorforge.providers.ollama.OllamaProvider.generate", generate)
    owner = Principal("fixture", "synthesis-owner", frozenset({"execute_research"}))
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        request = prepare_synthesis_fixture(Path(__file__).resolve().parents[2], artifacts)
        if qwen_extraction:
            request = QwenSynthesisResearchRequest.model_validate_json(
                request.model_copy(
                    update={"schema_version": "synthesis-research-request-v2"}
                ).model_dump_json()
            )
        run = store.create(request.brief, "synthesis", owner)
        if outcome == "pending":

            def crash(stage: str) -> None:
                """An uncertain reservation cannot become permission for a fresh provider call."""
                if stage == "after_synthesis_reservation":
                    raise RuntimeError("synthesis reservation interruption")

            store.failpoint = crash
            with pytest.raises(RuntimeError, match="synthesis reservation interruption"):
                execute_synthesis_research(store, run.run_id, owner, request, artifacts)
            store.failpoint = None
            with pytest.raises(ResearchError) as unresolved:
                execute_synthesis_research(store, run.run_id, owner, request, artifacts)
            assert unresolved.value.code == "RESEARCH_OPERATION_UNRESOLVED"
            assert len(calls) == 4
            return
        result = execute_synthesis_research(store, run.run_id, owner, request, artifacts)
        assert result.status == ("completed" if outcome == "completed" else "held")
        assert (result.hybrid is not None) == (outcome == "completed")
        assert len(calls) == (4 if outcome == "uncertain_review" else 5)
        grade = grade_synthesis(publish(result, artifacts), artifacts)
        assert grade["passed"] == (outcome == "completed")
        assert grade["checks"]["operation_limits"] is True
        before = read_budget(store, run.run_id, owner)
        assert sum(row.operation.kind == "experiment" for row in before.operations) == int(
            outcome == "completed"
        )

        def no_repeat(*args: object, **kwargs: object) -> None:
            """The entire second invocation must recover settled providers and accounting."""
            raise AssertionError("duplicate synthesis dispatch")

        monkeypatch.setattr("factorforge.providers.ollama.OllamaProvider.generate", no_repeat)
        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        assert execute_synthesis_research(store, run.run_id, owner, request, artifacts) == result
        assert read_budget(store, run.run_id, owner) == before
