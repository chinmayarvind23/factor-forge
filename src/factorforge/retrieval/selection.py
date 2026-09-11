"""A bounded reviewed literature catalog connects lexical hits to exact extraction packets."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.literature import LexicalHit, PaperDocument
from factorforge.retrieval.extraction import SourcePacket
from factorforge.retrieval.lexical import BM25Index


class LiteratureEntry(Contract):
    """Trusted ingestion binds indexed metadata to reviewed physical-page references."""

    document: PaperDocument
    source: SourcePacket

    @model_validator(mode="after")
    def source_identity(self) -> Self:
        """An original summary is not itself a source page or permission to substitute one."""
        if (
            self.document.paper_id != self.source.paper_id
            or self.document.source_sha256 != self.source.source_sha256
        ):
            raise ValueError("Indexed paper and extraction source must have the same identity")
        return self


class LiteratureCatalog(Contract):
    """One immutable catalog bounds local retrieval; source acquisition is an ingestion task."""

    schema_version: Literal["literature-source-catalog-v1"] = "literature-source-catalog-v1"
    entries: Annotated[tuple[LiteratureEntry, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_papers(self) -> Self:
        """Each ranked paper ID resolves to one reviewed packet without ambiguous overwrite."""
        if len({entry.document.paper_id for entry in self.entries}) != len(self.entries):
            raise ValueError("Catalog paper identities must be unique")
        return self


class SourceSelection(Contract):
    """Retain the ranking and chosen packets without claiming semantic relevance or extraction."""

    schema_version: Literal["literature-source-selection-v1"] = "literature-source-selection-v1"
    policy: Literal["positive-bm25-first-three-v1"] = "positive-bm25-first-three-v1"
    catalog: ArtifactRef
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    hits: Annotated[tuple[LexicalHit, ...], Field(max_length=20)]
    sources: Annotated[tuple[SourcePacket, ...], Field(max_length=3)]

    @model_validator(mode="after")
    def selected_prefix(self) -> Self:
        """Saved selection must preserve the exact ranked prefix and corresponding source hashes."""
        if len(self.sources) != min(3, len(self.hits)) or len(
            {hit.document.paper_id for hit in self.hits}
        ) != len(self.hits):
            raise ValueError("Selection inventory is inconsistent")
        for packet, hit in zip(self.sources, self.hits[:3], strict=True):
            if (
                packet.paper_id != hit.document.paper_id
                or packet.source_sha256 != hit.document.source_sha256
            ):
                raise ValueError("Selected source does not match the ranked paper")
        return self


def _publish(store: ArtifactStore, value: Contract) -> ArtifactRef:
    """Bind canonical metadata publication to exact bytes before returning its identity."""
    raw = value.canonical_bytes()
    if len(raw) > 4 * 2**20:
        raise ResearchError("CORPUS_TOO_LARGE", "Literature metadata exceeds its byte limit.", 413)
    expected = ArtifactRef(
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json"
    )
    if store.put(raw, media_type="application/json") != expected:
        raise ResearchError(
            "LITERATURE_EVIDENCE_INVALID", "Literature evidence cannot be verified.", 409
        )
    return expected


def select_sources(query: str, catalog: LiteratureCatalog, store: ArtifactStore) -> SourceSelection:
    """Rank the frozen index and retain up to three packets without fetching or model calls."""
    catalog = LiteratureCatalog.model_validate(catalog)
    index = BM25Index(entry.document for entry in catalog.entries)
    hits = index.search(query, limit=20)
    packets = {entry.document.paper_id: entry.source for entry in catalog.entries}
    selected = SourceSelection(
        catalog=_publish(store, catalog),
        query=query,
        hits=hits,
        sources=tuple(packets[hit.document.paper_id] for hit in hits[:3]),
    )
    _publish(store, selected)
    return selected
