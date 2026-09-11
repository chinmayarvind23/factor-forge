"""Schedule source-derived monthly experiments through durable per-command graphs."""

from fractions import Fraction
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from factorforge.auth.principal import Principal
from factorforge.backtests.funding import exact_quantity
from factorforge.backtests.monthly import MonthlyRequest
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.performance import Instant, Positive
from factorforge.orchestration.direction_review_worker import (
    DirectionReviewCommand,
    execute_direction_review_operation,
)
from factorforge.orchestration.monthly_graph import MonthlyExperimentGraph
from factorforge.orchestration.monthly_worker import recover_monthly_operation
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_strategies import (
    ReviewedStrategyBinding,
    _publish,
    research_strategies,
)
from factorforge.retrieval.selection import LiteratureCatalog
from factorforge.validation.monthly import MonthlyHACRequest, validate_monthly_hac


class ExperimentPlan(Contract):
    """Capture the controller's clock and capital once so retry cannot change operation identity."""

    schema_version: Literal["research-experiment-plan-v1"] = "research-experiment-plan-v1"
    catalog: LiteratureCatalog
    bindings: Annotated[tuple[ReviewedStrategyBinding, ...], Field(max_length=32)]
    initial_cash_usd: Positive
    evaluated_at: Instant
    max_cost_per_source_microusd: Annotated[int, Field(ge=1, le=100000000)]
    hac_lags: Annotated[int, Field(ge=0, le=120)] | None = None
    hac_correction: Literal["none", "n_over_n_minus_one"] = "none"

    @model_validator(mode="after")
    def supported_capital(self) -> Self:
        """Reject capital outside the ledger's exact precision before any provider work."""
        exact_quantity(Fraction(self.initial_cash_usd))
        return self


class ScheduledExperiment(Contract):
    """The source-order index links execution or an explicit skip to its published candidate."""

    candidate_index: Annotated[int, Field(ge=0, le=2)]
    status: Literal["completed", "failed", "skipped", "budget_stopped"]
    result: ArtifactRef | None
    reason: str | None
    validation: ArtifactRef | None = None


class ReviewedExperimentPlan(Contract):
    """Version the added review policy without changing canonical bytes of existing plans."""

    schema_version: Literal["research-experiment-plan-v2"] = "research-experiment-plan-v2"
    execution: ExperimentPlan
    max_cost_per_review_microusd: Annotated[int, Field(ge=1, le=100000000)]


class CandidateDirectionReview(Contract):
    """Retain the source-order judgment separately from the unchanged extraction artifact."""

    candidate_index: Annotated[int, Field(ge=0, le=2)]
    review: ArtifactRef
    agrees: bool


class ResearchExperiments(Contract):
    """Retain the exact plan, source-stage artifact and ordered experiment outcomes."""

    schema_version: Literal["research-experiments-v1"] = "research-experiments-v1"
    run_id: UUID
    plan: ExperimentPlan
    strategies: ArtifactRef
    experiments: Annotated[tuple[ScheduledExperiment, ...], Field(max_length=3)]


class ReviewedResearchExperiments(Contract):
    """Bind the review policy and judgments to the resulting experiment inventory."""

    schema_version: Literal["research-experiments-v2"] = "research-experiments-v2"
    plan: ReviewedExperimentPlan
    execution: ResearchExperiments
    reviews: Annotated[tuple[CandidateDirectionReview, ...], Field(max_length=3)]


def research_experiments(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    plan: ExperimentPlan | ReviewedExperimentPlan,
    artifacts: ArtifactStore,
) -> ResearchExperiments | ReviewedResearchExperiments:
    """Execute compiled candidates serially in source order under original durable budgets.

    The stage recomputes deterministic selection/compilation and resumes each monthly graph.
    Pending operations require reconciliation; only explicit budget rejection becomes a
    scheduling outcome. No generated code, model decision or checkpoint grants execution rights.
    """
    principal.require("execute_research")
    review_plan = (
        ReviewedExperimentPlan.model_validate(plan)
        if isinstance(plan, ReviewedExperimentPlan)
        else None
    )
    plan = ExperimentPlan.model_validate(review_plan.execution if review_plan is not None else plan)
    strategies = research_strategies(
        runs,
        run_id,
        principal,
        plan.catalog,
        plan.bindings,
        artifacts,
        max_cost_per_source_microusd=plan.max_cost_per_source_microusd,
    )
    strategy_ref = _publish(strategies, artifacts)
    results = []
    reviews = []
    for index, candidate in enumerate(strategies.candidates):
        if (
            candidate.status != "compiled"
            or candidate.draft is None
            or candidate.draft.strategy is None
        ):
            results.append(
                ScheduledExperiment(
                    candidate_index=index, status="skipped", result=None, reason=candidate.status
                )
            )
            continue
        command = MonthlyRequest(
            spec=candidate.draft.strategy,
            initial_cash_usd=plan.initial_cash_usd,
            evaluated_at=plan.evaluated_at,
        )
        try:
            if review_plan is not None:
                review = execute_direction_review_operation(
                    runs,
                    run_id,
                    principal,
                    DirectionReviewCommand(
                        source=strategies.sources.selection.sources[index],
                        max_cost_microusd=review_plan.max_cost_per_review_microusd,
                    ),
                    artifacts,
                )
                agrees = (
                    review.status == "supported"
                    and review.observation is not None
                    and review.observation.direction
                    == candidate.draft.request.observation.long_short_direction
                )
                reviews.append(
                    CandidateDirectionReview(
                        candidate_index=index, review=_publish(review, artifacts), agrees=agrees
                    )
                )
                if not agrees:
                    results.append(
                        ScheduledExperiment(
                            candidate_index=index,
                            status="skipped",
                            result=None,
                            reason="DIRECTION_REVIEW_DISAGREEMENT"
                            if review.status == "supported"
                            else "DIRECTION_REVIEW_" + review.status.upper(),
                        )
                    )
                    continue
            reference = MonthlyExperimentGraph(runs, run_id, principal, command, artifacts).finish()
        except ResearchError as error:
            if error.code != "RESEARCH_BUDGET_REJECTED":
                raise
            results.append(
                ScheduledExperiment(
                    candidate_index=index, status="budget_stopped", result=None, reason=error.code
                )
            )
            continue
        settled = recover_monthly_operation(runs, run_id, principal, command, artifacts)
        validation = None
        if plan.hac_lags is not None:
            diagnostic = validate_monthly_hac(
                MonthlyHACRequest(
                    result=reference, lags=plan.hac_lags, correction=plan.hac_correction
                ),
                artifacts,
            )
            validation = _publish(diagnostic, artifacts)
        results.append(
            ScheduledExperiment(
                candidate_index=index,
                status=settled.status,
                result=reference,
                reason=settled.failure_code,
                validation=validation,
            )
        )
    result = ResearchExperiments(
        run_id=run_id, plan=plan, strategies=strategy_ref, experiments=tuple(results)
    )
    if review_plan is not None:
        reviewed = ReviewedResearchExperiments(
            plan=review_plan, execution=result, reviews=tuple(reviews)
        )
        _publish(reviewed, artifacts)
        return reviewed
    _publish(result, artifacts)
    return result
