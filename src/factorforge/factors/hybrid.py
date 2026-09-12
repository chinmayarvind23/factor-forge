"""Compose explicitly weighted, direction-aligned source strategies without hidden rescaling."""

import json
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationError, model_validator

from factorforge.data.artifacts import ArtifactStore, reference
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.raw_strategy import MonthlyInput, RawStrategySpec
from factorforge.domain.targets import Rational
from factorforge.lineage.closure import verify_closure


class HybridComponent(Contract):
    """Positive weights express contribution after the parent's direction is aligned."""

    strategy: RawStrategySpec
    weight: Rational


class HybridRequest(Contract):
    """The caller declares comparable score scales; no fitted transformation uses future data."""

    schema_version: Literal["hybrid-strategy-request-v1"] = "hybrid-strategy-request-v1"
    name: Annotated[str, Field(min_length=1, max_length=200)]
    rationale: Annotated[str, Field(min_length=3, max_length=2000)]
    scale_policy: Literal["caller_declared_comparable_raw_scores_v1"] = (
        "caller_declared_comparable_raw_scores_v1"
    )
    components: Annotated[tuple[HybridComponent, ...], Field(min_length=2, max_length=4)]

    @model_validator(mode="after")
    def exact_mix(self) -> Self:
        """Bound rational complexity and reject duplicate hypotheses or implicit leverage."""
        weights = [component.weight.as_fraction() for component in self.components]
        if any(not 0 < value <= 1 or value.denominator > 1000000 for value in weights):
            raise ValueError("Hybrid weights must be positive bounded fractions")
        if sum(weights, Fraction(0)) != 1:
            raise ValueError("Hybrid weights must sum exactly to one")
        if len({component.strategy.sha256 for component in self.components}) != len(weights):
            raise ValueError("Hybrid components must identify distinct source strategies")
        return self


class HybridDraft(Contract):
    """A retained proposal can be held without pretending that incompatible inputs were merged."""

    schema_version: Literal["hybrid-strategy-draft-v1"] = "hybrid-strategy-draft-v1"
    request: HybridRequest
    parents: tuple[ArtifactRef, ...]
    strategy: RawStrategySpec | None
    reasons: tuple[str, ...]


def publish(value: Contract, store: ArtifactStore) -> ArtifactRef:
    """Require publication to preserve exact canonical bytes before linking derived evidence."""
    raw = value.canonical_bytes()
    expected = reference(raw, "application/json", 8 * 2**20)
    if store.put(raw, media_type="application/json") != expected:
        raise ResearchError("HYBRID_EVIDENCE_INVALID", "Hybrid evidence cannot be retained.", 409)
    return expected


def _environment(strategy: RawStrategySpec) -> dict[str, object]:
    """Only formula, signal bindings, provenance and raw direction may differ between parents."""
    wire = strategy.model_dump(mode="json")
    for key in ("factor_id", "version", "name", "source_refs", "signal_inputs", "formula"):
        wire.pop(key)
    wire["portfolio"]["allocation"].pop("direction")
    return wire


def compile_hybrid(request: HybridRequest, store: ArtifactStore) -> HybridDraft:
    """Merge compatible source formulas into the existing bounded arithmetic execution profile.

    Inputs keep their original names, units, availability rules and data bindings. Conflicting
    meanings cannot be renamed into apparent compatibility. Score comparability is a declared
    hypothesis, not a statistical result; rank normalization and fitted weights are not inferred.
    """
    request = HybridRequest.model_validate(request)
    parents = tuple(publish(component.strategy, store) for component in request.components)
    for parent in parents:
        verify_closure(parent, store)
    request_ref = publish(request, store)
    base = request.components[0].strategy
    reasons: list[str] = []
    inputs: dict[str, MonthlyInput] = {}
    terms: list[str] = []
    sources = {ref.sha256: ref for ref in (*parents, request_ref)}
    for component in request.components:
        strategy = component.strategy
        if _environment(strategy) != _environment(base):
            reasons.append("incompatible_execution_environment")
        for binding in strategy.signal_inputs:
            if binding.name in inputs and inputs[binding.name] != binding:
                reasons.append("conflicting_input_binding")
            inputs[binding.name] = binding
        for ref in strategy.source_refs:
            sources[ref.sha256] = ref
        weight = component.weight
        sign = "" if strategy.portfolio.allocation.direction == "long_high_short_low" else "-"
        terms.append(f"({weight.numerator}/{weight.denominator})*({sign}({strategy.formula}))")
    if reasons:
        draft = HybridDraft(
            request=request, parents=parents, strategy=None, reasons=tuple(sorted(set(reasons)))
        )
    else:
        wire = base.model_dump(mode="json")
        wire.update(
            factor_id="hybrid-" + request.sha256,
            version="v1",
            name=request.name,
            formula="+".join(terms),
            signal_inputs=[inputs[key].model_dump(mode="json") for key in sorted(inputs)],
            source_refs=[sources[key].model_dump(mode="json") for key in sorted(sources)],
        )
        wire["portfolio"]["allocation"]["direction"] = "long_high_short_low"
        try:
            strategy = RawStrategySpec.model_validate_json(json.dumps(wire))
        except ValidationError:
            draft = HybridDraft(
                request=request,
                parents=parents,
                strategy=None,
                reasons=("invalid_composed_contract",),
            )
        else:
            draft = HybridDraft(request=request, parents=parents, strategy=strategy, reasons=())
    publish(draft, store)
    return draft
