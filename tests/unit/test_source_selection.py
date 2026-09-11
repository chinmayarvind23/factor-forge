"""Original literature records exercise deterministic ranking and source-packet binding."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.literature import PaperDocument
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry, select_sources


def entry(identifier: str, text: str = "Original momentum strategy") -> LiteratureEntry:
    """Declared source pages are test metadata; no external paper or expected strategy is read."""
    return LiteratureEntry(
        document=PaperDocument(
            paper_id=identifier,
            title=text,
            text=text,
            source_url="https://example.org/original",
            source_sha256="a" * 64,
            content_kind="original_summary",
            source_version="original-v1",
        ),
        source=SourcePacket(
            paper_id=identifier,
            source_sha256="a" * 64,
            selected_strategy=text,
            pages=(
                SourcePage(
                    pdf_page=1,
                    artifact=ArtifactRef(sha256="b" * 64, size_bytes=10, media_type="text/plain"),
                ),
            ),
        ),
    )


def test_ranked_packets_are_deterministic_and_retained() -> None:
    """Tie ordering follows the existing BM25 rule and the first three packets match those hits."""
    catalog = LiteratureCatalog(
        entries=tuple(entry(identifier) for identifier in ("d", "b", "a", "c"))
    )
    with TemporaryDirectory() as directory:
        store = LocalArtifactStore(Path(directory))
        result = select_sources("momentum", catalog, store)
        assert [hit.document.paper_id for hit in result.hits] == ["a", "b", "c", "d"]
        assert [source.paper_id for source in result.sources] == ["a", "b", "c"]
        assert store.get(result.catalog) == catalog.canonical_bytes()
        assert select_sources("momentum", catalog, store) == result


def test_no_hits_produces_empty_source_selection() -> None:
    """No lexical match creates no implicit fallback or provider work."""
    with TemporaryDirectory() as directory:
        result = select_sources(
            "unrelatedterm",
            LiteratureCatalog(entries=(entry("a"),)),
            LocalArtifactStore(Path(directory)),
        )
        assert result.hits == () and result.sources == ()


@pytest.mark.parametrize("field,value", [("paper_id", "other"), ("source_sha256", "c" * 64)])
def test_packet_must_match_indexed_source_identity(field: str, value: str) -> None:
    """A selected document cannot silently substitute a different extraction packet."""
    original = entry("a")
    with pytest.raises(ValidationError):
        LiteratureEntry(
            document=original.document, source=original.source.model_copy(update={field: value})
        )


def test_catalog_rejects_duplicate_paper_identity() -> None:
    """A ranking hit must resolve to exactly one packet."""
    with pytest.raises(ValidationError):
        LiteratureCatalog(entries=(entry("a"), entry("a")))
