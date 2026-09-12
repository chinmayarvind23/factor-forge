"""Canonical operator requests are shared by the CLI and durable research workflow."""

from pydantic import Field

from factorforge.domain.factors import Contract
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.research_experiments import (
    ExperimentPlan,
    IterativeExperimentPlan,
    ReviewedExperimentPlan,
)


class OperatorRequest(Contract):
    """A complete retained brief and plan define the operator's stable idempotency key."""

    brief: ResearchBrief
    plan: ExperimentPlan | ReviewedExperimentPlan | IterativeExperimentPlan = Field(
        discriminator="schema_version"
    )
