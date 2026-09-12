"""The canonical research idea selects retained literature packets for budgeted extraction."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.orchestration.extraction_worker import (
    ExtractionCommand,
    QwenExtractionCommand,
    execute_extraction_operation,
)
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.retrieval.extraction import ExtractionResult
from factorforge.retrieval.selection import LiteratureCatalog, SourceSelection, select_sources


class ResearchSources(Contract):
    """Each selected packet retains one typed outcome in the original ranking order."""

    run_id: UUID
    selection: SourceSelection
    extractions: Annotated[tuple[ExtractionResult, ...], Field(max_length=3)]

    @model_validator(mode="after")
    def complete_inventory(self) -> Self:
        """A source-stage result cannot silently omit a selected provider outcome."""
        if len(self.extractions) != len(self.selection.sources):
            raise ValueError("Every selected source requires its extraction outcome")
        return self


def research_sources(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    catalog: LiteratureCatalog,
    artifacts: ArtifactStore,
    *,
    max_cost_per_source_microusd: int,
    extraction_model: Literal["llama3.1:8b", "qwen3:8b"] = "llama3.1:8b",
) -> ResearchSources:
    """Retrieve from the canonical idea and process the selected packets through durable workers.

    Deterministic retrieval may replay; each model operation independently reuses its durable
    result. If an attempt has an unresolved reservation, execution stops for reconciliation.
    The caller supplies a reviewed catalog, never arbitrary network or filesystem destinations.
    """
    principal.require("execute_research")
    if (
        type(max_cost_per_source_microusd) is not int
        or not 0 < max_cost_per_source_microusd <= 100000000
    ):
        raise ResearchError("RESEARCH_BUDGET_REJECTED", "The extraction allowance is invalid.", 409)
    read_budget(runs, run_id, principal)
    canonical = runs.get(run_id, principal)
    selection = select_sources(canonical.idea, catalog, artifacts)
    results = tuple(
        execute_extraction_operation(
            runs,
            run_id,
            principal,
            (QwenExtractionCommand if extraction_model == "qwen3:8b" else ExtractionCommand)(
                source=source, max_cost_microusd=max_cost_per_source_microusd
            ),
            artifacts,
        )
        for source in selection.sources
    )
    result = ResearchSources(run_id=run_id, selection=selection, extractions=results)
    raw = result.canonical_bytes()
    expected = ArtifactRef(
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json"
    )
    if len(raw) > 4 * 2**20 or artifacts.put(raw, media_type="application/json") != expected:
        raise ResearchError(
            "LITERATURE_EVIDENCE_INVALID", "Literature evidence cannot be verified.", 409
        )
    return result
