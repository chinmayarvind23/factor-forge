"""Admit a permitted local PDF into the existing reviewed source catalog."""

import argparse
import subprocess
from pathlib import Path
from tempfile import TemporaryFile
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.domain.literature import PaperDocument
from factorforge.lineage.closure import verify_closure
from factorforge.retrieval.discovery import DiscoveryResult, replay
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry, _publish

_PARSER_WRAPPER = """
import subprocess, sys, tempfile
with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
    result = subprocess.run(['pdftotext', *sys.argv[1:]],
        input=sys.stdin.buffer.read(8388609), stdout=output, stderr=errors, timeout=25)
    if result.returncode:
        sys.exit(1)
    output.seek(0)
    raw = output.read(1048577)
    if len(raw) > 1048576:
        sys.exit(1)
    sys.stdout.buffer.write(raw)
"""


class AdmissionRequest(Contract):
    """The local operator attests identity and permitted use before parsing selected pages."""

    schema_version: Literal["source-admission-request-v1"] = "source-admission-request-v1"
    discovery: ArtifactRef
    pdf: ArtifactRef
    doi: Annotated[str, Field(min_length=4, max_length=256)]
    paper_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    selected_strategy: Annotated[str, Field(min_length=1, max_length=500)]
    pages: Annotated[
        tuple[Annotated[int, Field(ge=1, le=10000)], ...], Field(min_length=1, max_length=16)
    ]
    identity_reviewed: Literal[True]
    rights: Literal["private_research_only", "redistribution_permitted"]

    @model_validator(mode="after")
    def bounded_pdf(self) -> Self:
        """Reject ambiguous page requests and oversized source files before process dispatch."""
        if self.pdf.media_type != "application/pdf" or self.pdf.size_bytes > 8 * 2**20:
            raise ValueError("Admission requires a PDF of at most eight MiB")
        if tuple(sorted(set(self.pages))) != self.pages or self.pages[-1] - self.pages[0] > 31:
            raise ValueError("Pages must be sorted, unique, and within a 32-page span")
        return self


class SourceAdmission(Contract):
    """Retain the PDF, discovery, parser output, permission declaration and extraction catalog."""

    schema_version: Literal["source-admission-v1"] = "source-admission-v1"
    request: AdmissionRequest
    parser: Literal["poppler-pdftotext-layout-utf8-v1"] = "poppler-pdftotext-layout-utf8-v1"
    parser_version: ArtifactRef
    parsed_pages: ArtifactRef
    catalog: ArtifactRef


def _parse_pdf(raw: bytes, pages: tuple[int, ...], *, wsl: bool) -> tuple[bytes, bytes]:
    """Run Poppler with kernel CPU, address-space and output-file limits; never invoke a shell."""
    prefix = ["wsl.exe", "--exec"] if wsl else []
    limits = ["prlimit", "--as=536870912", "--cpu=20", "--fsize=1048576", "--"]
    with TemporaryFile() as output, TemporaryFile() as errors:
        result = subprocess.run(
            [
                *prefix,
                *limits,
                "python3",
                "-c",
                _PARSER_WRAPPER,
                "-f",
                str(pages[0]),
                "-l",
                str(pages[-1]),
                "-layout",
                "-enc",
                "UTF-8",
                "-",
                "-",
            ],
            input=raw,
            stdout=output,
            stderr=errors,
            timeout=30,
            check=False,
        )
        output.seek(0)
        parsed = output.read(2**20 + 1)
        if result.returncode or len(parsed) > 2**20:
            raise ValueError("PDF parser failed or exceeded its output limit")
    version = subprocess.run(
        [*prefix, *limits, "pdftotext", "-v"], capture_output=True, timeout=5, check=True
    )
    return parsed, (version.stdout + version.stderr)[:4096]


def admit_pdf(
    request: AdmissionRequest, store: ArtifactStore, *, wsl: bool = False
) -> SourceAdmission:
    """Convert verified source bytes into page-bound packets accepted by the existing selector."""
    request = AdmissionRequest.model_validate(request)
    discovery_raw = store.get(request.discovery)
    verify_bytes(discovery_raw, request.discovery)
    discovered = replay(DiscoveryResult.model_validate_json(discovery_raw), store)
    candidate = next(
        (item for item in discovered.candidates if item.doi.lower() == request.doi.lower()), None
    )
    if discovered.status != "success" or candidate is None:
        raise ValueError("Reviewed DOI is absent from the retained discovery")
    raw = store.get(request.pdf)
    verify_bytes(raw, request.pdf)
    if not raw.startswith(b"%PDF-"):
        raise ValueError("Source does not have a PDF header")
    parsed, version = _parse_pdf(raw, request.pages, wsl=wsl)
    chunks = parsed.decode("utf-8").split("\f")
    if len(chunks) != request.pages[-1] - request.pages[0] + 2 or chunks[-1].strip():
        raise ValueError("Parser output does not preserve the requested physical page range")
    pages = []
    for number in request.pages:
        text = chunks[number - request.pages[0]]
        if not text.strip():
            raise ValueError("Selected page has no extractable text; review or OCR is required")
        ref = store.put(text.encode("utf-8"), media_type="text/plain")
        verify_bytes(text.encode("utf-8"), ref)
        pages.append(SourcePage(pdf_page=number, artifact=ref))
    packet = SourcePacket(
        paper_id=request.paper_id,
        source_sha256=request.pdf.sha256,
        selected_strategy=request.selected_strategy,
        pages=tuple(pages),
    )
    document = PaperDocument(
        paper_id=request.paper_id,
        title=candidate.title,
        text="\n".join(chunks[number - request.pages[0]] for number in request.pages)[:16000],
        source_url="https://doi.org/" + candidate.doi,
        source_sha256=request.pdf.sha256,
        content_kind="source_passage",
        source_version=request.pdf.sha256,
    )
    catalog = LiteratureCatalog(entries=(LiteratureEntry(document=document, source=packet),))
    result = SourceAdmission(
        request=request,
        parser_version=store.put(version, media_type="text/plain"),
        parsed_pages=store.put(parsed, media_type="text/plain"),
        catalog=_publish(store, catalog),
    )
    verify_closure(_publish(store, result), store)
    return result


def main() -> None:
    """Use existing local artifact references; no source URL is fetched or permission inferred."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl", action="store_true")
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Admission request exceeds limit")
    with args.output.open("xb") as output:
        result = admit_pdf(
            AdmissionRequest.model_validate_json(raw),
            LocalArtifactStore(args.artifacts),
            wsl=args.wsl,
        )
        output.write(result.canonical_bytes())
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
