"""Compile source observations against explicitly reviewed monthly execution bindings."""

import json
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from factorforge.domain.extraction import SourceExtraction
from factorforge.domain.factors import Contract
from factorforge.domain.raw_strategy import RawStrategySpec


class SourceStrategyRequest(Contract):
    """The caller supplies data semantics and the source formation rule it reviewed.

    The environment is an explicit execution template, not evidence that source
    extraction is accurate. Its source references must retain the reviewed evidence.
    """

    schema_version: Literal["source-strategy-request-v1"] = "source-strategy-request-v1"
    environment: RawStrategySpec
    reviewed_formation_rule: Annotated[str, Field(min_length=1, max_length=2000)]
    observation: SourceExtraction


class SourceStrategyDraft(Contract):
    """Retain the entire input and unresolved choices alongside a possible strategy.

    This is a compiler result, not an admission receipt or a source-accuracy grade.
    Publication must retain this request with the upstream extraction evidence.
    """

    schema_version: Literal["source-strategy-draft-v1"] = "source-strategy-draft-v1"
    request: SourceStrategyRequest
    strategy: RawStrategySpec | None
    reasons: tuple[str, ...]


def compile_source_strategy(request: SourceStrategyRequest) -> SourceStrategyDraft:
    """Translate supported source choices without renaming inputs or inferring formation rules.

    A null lookback is retained; the raw contract independently requires a concrete
    sufficient lookback for historical formula calls. All market, unit, universe,
    sample, fee and funding choices remain explicit in the reviewed environment.
    """
    request = SourceStrategyRequest.model_validate(request)
    source = request.observation
    template = request.environment
    checks = (
        (source.status == "extracted", "source_refused"),
        (source.formula is not None, "missing_formula"),
        (
            set(source.required_inputs) == {row.name for row in template.signal_inputs},
            "input_binding_mismatch",
        ),
        (source.long_short_direction is not None, "missing_direction"),
        (source.bucket_count is not None, "missing_bucket_count"),
        (source.weighting == "equal_weight", "unsupported_weighting"),
        (source.holding_months == 1, "unsupported_holding_period"),
        (source.rebalance_frequency == "monthly", "unsupported_rebalance"),
        (source.formation_lag_months is not None, "missing_formation_lag"),
        (
            source.formation_rule == request.reviewed_formation_rule,
            "formation_rule_requires_review",
        ),
    )
    reasons = tuple(reason for accepted, reason in checks if not accepted)
    if reasons:
        return SourceStrategyDraft(request=request, strategy=None, reasons=reasons)
    wire = template.model_dump(mode="json")
    wire.update(factor_id=f"source-{request.sha256}", version="v1", formula=source.formula)
    wire["timing"].update(
        formation_lag_months=source.formation_lag_months,
        lookback_months=source.lookback_months,
    )
    wire["portfolio"]["allocation"].update(
        direction=source.long_short_direction,
        bucket_count=source.bucket_count,
        weighting=source.weighting,
    )
    try:
        strategy = RawStrategySpec.model_validate_json(json.dumps(wire))
    except ValidationError:
        return SourceStrategyDraft(
            request=request, strategy=None, reasons=("invalid_strategy_contract",)
        )
    return SourceStrategyDraft(request=request, strategy=strategy, reasons=())
