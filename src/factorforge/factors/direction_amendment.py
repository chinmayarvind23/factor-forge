"""Compile a separately identified direction amendment from retained revision evidence."""

from typing import Literal

from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction
from factorforge.domain.factors import Contract
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.factors.source_strategy import (
    SourceStrategyDraft,
    SourceStrategyRequest,
    compile_source_strategy,
)
from factorforge.retrieval.direction_review import DirectionReview
from factorforge.retrieval.direction_revision import DirectionRevisionRequest


class DirectionAmendmentRequest(Contract):
    """The original compiler output and all three observations define the proposed amendment."""

    schema_version: Literal["direction-amendment-request-v1"] = "direction-amendment-request-v1"
    original: SourceStrategyDraft
    conflict: DirectionRevisionRequest
    resolution: DirectionReview


class DirectionAmendment(Contract):
    """Retain the complete decision input even when no amended strategy can be compiled."""

    schema_version: Literal["direction-amendment-v1"] = "direction-amendment-v1"
    request: DirectionAmendmentRequest
    draft: SourceStrategyDraft | None
    reason: str | None


def amend_direction(request: DirectionAmendmentRequest) -> DirectionAmendment:
    """Change only direction after two cited judgments agree; never rewrite the original.

    The trusted coordinator supplies canonical worker results. This compiler enforces
    structural lineage and a fixed amendment policy, not semantic truth or execution rights.
    All formula, timing, costs, data and funding choices remain those of the original draft.
    """
    request = DirectionAmendmentRequest.model_validate(request)
    original = request.original
    initial = request.conflict.extraction.observation
    review = request.conflict.review.observation
    if (
        original.strategy is None
        or compile_source_strategy(original.request) != original
        or initial != original.request.observation
        or request.conflict.extraction.record not in original.request.environment.source_refs
    ):
        raise ResearchError(
            "DIRECTION_AMENDMENT_INVALID", "Original draft binding is invalid.", 422
        )
    resolution = request.resolution
    if resolution.status != "supported" or resolution.observation is None:
        return DirectionAmendment(
            request=request, draft=None, reason="revision_" + resolution.status
        )
    if review is None or resolution.observation.direction != review.direction:
        return DirectionAmendment(request=request, draft=None, reason="direction_not_confirmed")
    references = original.request.environment.source_refs
    for ref in (request.conflict.review.record, resolution.record):
        if ref not in references:
            references = (*references, ref)
    if len(references) > 32:
        return DirectionAmendment(request=request, draft=None, reason="source_reference_limit")
    environment = RawStrategySpec.model_validate(
        original.request.environment.model_copy(update={"source_refs": references})
    )
    observation = SourceExtraction.model_validate(
        original.request.observation.model_copy(
            update={"long_short_direction": resolution.observation.direction}
        )
    )
    draft = compile_source_strategy(
        SourceStrategyRequest(
            environment=environment,
            reviewed_formation_rule=original.request.reviewed_formation_rule,
            observation=observation,
        )
    )
    return DirectionAmendment(
        request=request,
        draft=draft,
        reason=None if draft.strategy is not None else "compilation_held",
    )
