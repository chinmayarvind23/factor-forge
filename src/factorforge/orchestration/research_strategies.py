"""Publish source-bound strategy candidates from durable extraction outcomes."""

import hashlib
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.factors.source_strategy import (
    SourceStrategyDraft,
    SourceStrategyRequest,
    compile_source_strategy,
)
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_sources import ResearchSources, research_sources
from factorforge.retrieval.extraction import SourcePacket
from factorforge.retrieval.selection import LiteratureCatalog


class ReviewedStrategyBinding(Contract):
    """Reviewed data and formation semantics apply only to this exact source packet."""

    source: SourcePacket
    environment: RawStrategySpec
    reviewed_formation_rule: Annotated[str, Field(min_length=1, max_length=2000)]


class ReviewedStrategyBindingWithAliases(ReviewedStrategyBinding):
    """Optional, upfront reviewed source wording; never populated from model observations."""

    reviewed_formation_rule_aliases: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=2000)], ...],
        Field(min_length=1, max_length=4),
    ]


StrategyBinding = ReviewedStrategyBinding | ReviewedStrategyBindingWithAliases
_BINDING: TypeAdapter[StrategyBinding] = TypeAdapter(StrategyBinding)


def approved_formation_rule(
    binding: StrategyBinding, observed: str | None, artifacts: ArtifactStore
) -> str:
    """Select an exact reviewed alternative only after verifying its literal source membership.

    Plain bindings retain their original exact-match behavior and canonical identity.
    Aliases do not change typed timing fields, formulas or the strategy compiler's checks.
    """
    if isinstance(binding, ReviewedStrategyBindingWithAliases):
        pages = []
        for page in binding.source.pages:
            raw = artifacts.get(page.artifact)
            verify_bytes(raw, page.artifact)
            pages.append(" ".join(raw.decode("utf-8").split()))
        for alias in binding.reviewed_formation_rule_aliases:
            normalized = " ".join(alias.split())
            if not normalized or not any(normalized in page for page in pages):
                raise ValueError("Reviewed formation alias is absent from its source")
        if observed in binding.reviewed_formation_rule_aliases:
            return observed
    return binding.reviewed_formation_rule


class StrategyCandidate(Contract):
    """Preserve selected sources even when execution bindings or observations are unavailable."""

    status: Literal["compiled", "needs_review", "unbound", "source_unavailable"]
    draft: SourceStrategyDraft | None
    artifact: ArtifactRef | None


class ResearchStrategies(Contract):
    """The published stage retains ranking, extraction and every candidate in matching order."""

    schema_version: Literal["research-strategies-v1"] = "research-strategies-v1"
    sources: ResearchSources
    bindings: Annotated[tuple[StrategyBinding, ...], Field(max_length=32)]
    candidates: Annotated[tuple[StrategyCandidate, ...], Field(max_length=3)]


def _publish(value: Contract, artifacts: ArtifactStore) -> ArtifactRef:
    """Bound canonical publication and verify the store's returned content identity."""
    raw = value.canonical_bytes()
    expected = ArtifactRef(
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json"
    )
    if len(raw) > 4 * 2**20 or artifacts.put(raw, media_type="application/json") != expected:
        raise ResearchError(
            "STRATEGY_EVIDENCE_INVALID", "Strategy evidence cannot be verified.", 409
        )
    return expected


def research_strategies(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    catalog: LiteratureCatalog,
    bindings: tuple[StrategyBinding, ...],
    artifacts: ArtifactStore,
    *,
    max_cost_per_source_microusd: int,
    extraction_model: Literal["llama3.1:8b", "qwen3:8b"] = "llama3.1:8b",
) -> ResearchStrategies:
    """Compose canonical source retrieval, durable extraction and deterministic draft publication.

    Bindings are reviewed ingestion configuration, never model output. Exact packet equality
    prevents a paper ID from transferring approval to revised pages or another selected strategy.
    Replaying this stage reuses settled provider results and content-addressed publications.
    """
    principal.require("execute_research")
    catalog = LiteratureCatalog.model_validate(catalog)
    if type(bindings) is not tuple or len(bindings) > 32:
        raise ResearchError("STRATEGY_BINDING_INVALID", "Strategy bindings are invalid.", 422)
    bindings = tuple(_BINDING.validate_python(row) for row in bindings)
    by_id = {row.source.paper_id: row for row in bindings}
    catalog_sources = {row.source.paper_id: row.source for row in catalog.entries}
    if len(by_id) != len(bindings) or any(
        catalog_sources.get(row.source.paper_id) != row.source for row in bindings
    ):
        raise ResearchError("STRATEGY_BINDING_INVALID", "Strategy bindings are invalid.", 422)
    for reviewed_binding in bindings:
        approved_formation_rule(reviewed_binding, None, artifacts)
    sources = research_sources(
        runs,
        run_id,
        principal,
        catalog,
        artifacts,
        max_cost_per_source_microusd=max_cost_per_source_microusd,
        extraction_model=extraction_model,
    )
    candidates = []
    for source, extraction in zip(sources.selection.sources, sources.extractions, strict=True):
        binding = by_id.get(source.paper_id)
        if binding is None:
            candidates.append(StrategyCandidate(status="unbound", draft=None, artifact=None))
            continue
        if extraction.observation is None:
            candidates.append(
                StrategyCandidate(status="source_unavailable", draft=None, artifact=None)
            )
            continue
        environment = binding.environment
        references = environment.source_refs
        if isinstance(binding, ReviewedStrategyBindingWithAliases):
            references = (*references, _publish(binding, artifacts))
        if extraction.record not in references:
            references = (*references, extraction.record)
        environment = RawStrategySpec.model_validate(
            environment.model_copy(update={"source_refs": references})
        )
        draft = compile_source_strategy(
            SourceStrategyRequest(
                environment=environment,
                reviewed_formation_rule=approved_formation_rule(
                    binding, extraction.observation.formation_rule, artifacts
                ),
                observation=extraction.observation,
            )
        )
        candidates.append(
            StrategyCandidate(
                status="compiled" if draft.strategy is not None else "needs_review",
                draft=draft,
                artifact=_publish(draft, artifacts),
            )
        )
    result = ResearchStrategies(sources=sources, bindings=bindings, candidates=tuple(candidates))
    _publish(result, artifacts)
    return result
