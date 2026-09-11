"""Shared local report export for offline inspection and the trusted research operator."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from factorforge.data.artifacts import LocalArtifactStore, reference
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.orchestration.research_report import build_report, render_report
from factorforge.orchestration.research_strategies import _publish


class ReportExport(Contract):
    """Content identities describe report artifacts independently of their local export path."""

    report: ArtifactRef
    markdown: ArtifactRef


class ResearchCompletion(Contract):
    """A publication receipt binds the complete operator request to result and report evidence."""

    schema_version: Literal["research-completion-v1"] = "research-completion-v1"
    run_id: UUID
    request: ArtifactRef
    result: ArtifactRef
    budget: ArtifactRef
    report: ArtifactRef
    markdown: ArtifactRef


def export_report(result: ArtifactRef, store: LocalArtifactStore) -> tuple[ReportExport, Path]:
    """Reuse identical exports and reject conflicting local files without overwriting evidence."""
    report = build_report(result, store)
    report_ref = _publish(report, store)
    markdown = render_report(report).encode()
    expected = reference(markdown, "text/markdown", 2**20)
    if store.put(markdown, media_type="text/markdown") != expected:
        raise ResearchError("REPORT_EXPORT_INVALID", "Report export cannot be verified.", 409)
    path = store.root / ("report-" + report.sha256 + ".md")
    try:
        with path.open("xb") as output:
            output.write(markdown)
    except FileExistsError:
        with path.open("rb") as source:
            existing = source.read(len(markdown) + 1)
        if existing != markdown:
            raise ResearchError(
                "REPORT_EXPORT_INVALID", "Existing report export differs.", 409
            ) from None
    return ReportExport(report=report_ref, markdown=expected), path
