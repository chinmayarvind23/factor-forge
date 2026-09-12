"""Connect an idea and reviewed source catalog to model-proposed hybrid research execution."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.performance import Instant, Positive
from factorforge.domain.research_brief import ResearchBrief
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.command import OPERATOR
from factorforge.orchestration.direction_review_worker import (
    DirectionReviewCommand,
    execute_direction_review_operation,
)
from factorforge.orchestration.hybrid_command import HybridExperimentRequest, execute_hybrid
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_strategies import (
    StrategyBinding,
    research_strategies,
)
from factorforge.orchestration.synthesis_worker import SynthesisCommand, execute_synthesis_operation
from factorforge.retrieval.selection import LiteratureCatalog
from factorforge.retrieval.synthesis import SynthesisCandidate, SynthesisRequest


class _SynthesisResearchFields(Contract):
    """The operator supplies source/data bindings; the model selects the actual composition."""

    brief: ResearchBrief
    catalog: LiteratureCatalog
    bindings: Annotated[tuple[StrategyBinding, ...], Field(max_length=32)]
    initial_cash_usd: Positive
    evaluated_at: Instant
    max_cost_per_model_microusd: Annotated[int, Field(ge=1, le=100000000)] = 1000000


class SynthesisResearchRequest(_SynthesisResearchFields):
    """Original profile retains Llama extraction and direction review without changed identities."""

    schema_version: Literal["synthesis-research-request-v1"] = "synthesis-research-request-v1"


class QwenSynthesisResearchRequest(_SynthesisResearchFields):
    """Opt-in Qwen extraction changes only its recorded profile; review remains independent."""

    schema_version: Literal["synthesis-research-request-v2"] = "synthesis-research-request-v2"


_REQUEST: TypeAdapter[SynthesisResearchRequest | QwenSynthesisResearchRequest] = TypeAdapter(
    Annotated[
        SynthesisResearchRequest | QwenSynthesisResearchRequest,
        Field(discriminator="schema_version"),
    ]
)


class SynthesisResearchResult(Contract):
    """Retain every source-stage outcome and the composed experiment, including abstentions."""

    schema_version: Literal["synthesis-research-result-v1"] = "synthesis-research-result-v1"
    run_id: UUID
    request: ArtifactRef
    strategies: ArtifactRef | None
    reviews: tuple[ArtifactRef, ...]
    synthesis: ArtifactRef | None
    hybrid: ArtifactRef | None
    status: Literal["completed", "failed", "held", "budget_stopped"]
    reasons: tuple[str, ...]
    budget: ArtifactRef


def execute_synthesis_research(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    request: SynthesisResearchRequest | QwenSynthesisResearchRequest,
    artifacts: LocalArtifactStore,
) -> SynthesisResearchResult:
    """Run source extraction, independent direction review, synthesis and one durable hybrid.

    Model proposals cannot change data bindings, execution permissions or quant policy.
    Every model operation reserves before dispatch and replays through its canonical ledger.
    No automatic retry, response repair or hidden alternate synthesis attempt is permitted.
    """
    principal.require("execute_research")
    request = _REQUEST.validate_python(request)
    with runs._connection() as connection:
        owner = runs._owned(connection, run_id, principal)
        if ResearchBrief.model_validate(owner["request_json"]) != request.brief:
            raise ResearchError("SYNTHESIS_REQUEST_CONFLICT", "The run brief differs.", 409)
    request_ref = publish(request, artifacts)
    strategies_ref = synthesis_ref = hybrid_ref = None
    reviews: list[ArtifactRef] = []
    status: Literal["completed", "failed", "held", "budget_stopped"] = "held"
    reasons: tuple[str, ...] = ("INSUFFICIENT_REVIEWED_PARENTS",)
    try:
        strategies = research_strategies(
            runs,
            run_id,
            principal,
            request.catalog,
            request.bindings,
            artifacts,
            max_cost_per_source_microusd=request.max_cost_per_model_microusd,
            extraction_model="qwen3:8b"
            if isinstance(request, QwenSynthesisResearchRequest)
            else "llama3.1:8b",
        )
        strategies_ref = publish(strategies, artifacts)
        candidates = []
        for source, candidate in zip(
            strategies.sources.selection.sources, strategies.candidates, strict=True
        ):
            if (
                candidate.status != "compiled"
                or candidate.draft is None
                or candidate.draft.strategy is None
            ):
                continue
            review = execute_direction_review_operation(
                runs,
                run_id,
                principal,
                DirectionReviewCommand(
                    source=source, max_cost_microusd=request.max_cost_per_model_microusd
                ),
                artifacts,
            )
            reviews.append(publish(review, artifacts))
            if (
                review.status == "supported"
                and review.observation is not None
                and review.observation.direction
                == candidate.draft.strategy.portfolio.allocation.direction
            ):
                candidates.append(
                    SynthesisCandidate(
                        source=source, strategy=candidate.draft.strategy, review=review
                    )
                )
        if len(candidates) >= 2:
            synthesis = execute_synthesis_operation(
                runs,
                run_id,
                principal,
                SynthesisCommand(
                    request=SynthesisRequest(idea=request.brief.idea, candidates=tuple(candidates)),
                    max_cost_microusd=request.max_cost_per_model_microusd,
                ),
                artifacts,
            )
            synthesis_ref = publish(synthesis, artifacts)
            reasons = ("SYNTHESIS_" + synthesis.status.upper(),)
            if synthesis.proposal is not None:
                hybrid = execute_hybrid(
                    runs,
                    run_id,
                    principal,
                    HybridExperimentRequest(
                        brief=request.brief,
                        hybrid=synthesis.proposal,
                        initial_cash_usd=request.initial_cash_usd,
                        evaluated_at=request.evaluated_at,
                    ),
                    artifacts,
                )
                hybrid_ref = publish(hybrid, artifacts)
                status, reasons = hybrid.status, hybrid.reasons
    except ResearchError as error:
        if error.code != "RESEARCH_BUDGET_REJECTED":
            raise
        status, reasons = "budget_stopped", (error.code,)
    result = SynthesisResearchResult(
        run_id=run_id,
        request=request_ref,
        strategies=strategies_ref,
        reviews=tuple(reviews),
        synthesis=synthesis_ref,
        hybrid=hybrid_ref,
        status=status,
        reasons=reasons,
        budget=publish(read_budget(runs, run_id, principal), artifacts),
    )
    verify_closure(publish(result, artifacts), artifacts)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run or resume the complete source-to-hybrid pipeline from one retained local request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--schema", default="factorforge")
    args = parser.parse_args(argv)
    try:
        with args.request.open("rb") as source:
            raw = source.read(4 * 2**20 + 1)
        if len(raw) > 4 * 2**20:
            raise ValueError("Request exceeds limit")
        request = _REQUEST.validate_json(raw)
        dsn = os.environ.get("RDS_DSN")
        if not dsn:
            raise ResearchError("OPERATOR_DATABASE_REQUIRED", "RDS_DSN is required.", 422)
        artifacts = LocalArtifactStore(args.artifacts)
        runs = PostgresRunStore(dsn, schema=args.schema)
        try:
            run = runs.create(request.brief, "source-synthesis:" + request.sha256, OPERATOR)
            result = execute_synthesis_research(runs, run.run_id, OPERATOR, request, artifacts)
            print(
                json.dumps(
                    {
                        "run_id": str(run.run_id),
                        "result": publish(result, artifacts).model_dump(mode="json"),
                        "status": result.status,
                    }
                )
            )
        finally:
            runs.close()
    except ResearchError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}), file=sys.stderr
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "SYNTHESIS_EXECUTION_STOPPED",
                        "message": "Retain the request for reconciliation.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
