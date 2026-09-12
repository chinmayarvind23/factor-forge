"""Admission binds discovered identities to verified PDFs and physical source pages."""

import asyncio
import json

import httpx
import pytest
from test_monthly_admission import MemoryStore

from factorforge.domain.errors import ResearchError
from factorforge.retrieval.discovery import DiscoveryRequest, discover
from factorforge.retrieval.ingestion import AdmissionRequest, admit_pdf
from factorforge.retrieval.selection import LiteratureCatalog, select_sources


@pytest.mark.parametrize("mode", ["valid", "wrong_doi", "corrupt_pdf", "missing_page"])
def test_catalog_admission_and_selection(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Only a reviewed candidate with intact PDF and every requested page enters the catalog."""
    store = MemoryStore()
    result = asyncio.run(
        discover(
            DiscoveryRequest(query="momentum"),
            store,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "message": {
                            "items": [{"DOI": "10.1234/momentum", "title": ["Momentum research"]}]
                        },
                    },
                )
            ),
        )
    )
    discovery = store.put(result.canonical_bytes(), media_type="application/json")
    pdf = store.put(b"%PDF-original-test", media_type="application/pdf")
    request = AdmissionRequest(
        discovery=discovery,
        pdf=pdf,
        doi="10.1234/momentum" if mode != "wrong_doi" else "10.1234/other",
        paper_id="momentum",
        selected_strategy="momentum strategy",
        pages=(2, 3),
        identity_reviewed=True,
        rights="private_research_only",
    )

    def parser(raw: bytes, pages: tuple[int, ...], *, wsl: bool) -> tuple[bytes, bytes]:
        """Only verified source bytes and physical page indices reach the parser."""
        assert raw == b"%PDF-original-test" and pages == (2, 3)
        return (
            b"momentum page two\f"
            if mode == "missing_page"
            else b"momentum page two\fmomentum page three\f",
            b"pdftotext test-version",
        )

    monkeypatch.setattr("factorforge.retrieval.ingestion._parse_pdf", parser)
    if mode == "corrupt_pdf":
        store.values[pdf.sha256] = b"modified"
    if mode != "valid":
        with pytest.raises((ValueError, ResearchError)):
            admit_pdf(request, store)
        return
    admission = admit_pdf(request, store)
    catalog = LiteratureCatalog.model_validate_json(store.get(admission.catalog))
    selected = select_sources("momentum", catalog, store)
    assert [page.pdf_page for page in selected.sources[0].pages] == [2, 3]
    assert selected.sources[0].source_sha256 == pdf.sha256
    assert b"page two" in store.get(selected.sources[0].pages[0].artifact)
    assert (
        json.loads(store.get(admission.catalog))["entries"][0]["document"]["content_kind"]
        == "source_passage"
    )
