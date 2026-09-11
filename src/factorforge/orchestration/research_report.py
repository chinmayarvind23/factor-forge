"""Deterministic research outcome reports derived from retained, byte-verified evidence."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from factorforge.backtests.monthly import MonthlyRun
from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Identifier
from factorforge.domain.performance import Number
from factorforge.factors.direction_amendment import DirectionAmendment, amend_direction
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.research_experiments import (
    IterativeResearchExperiments,
    ResearchExperiments,
    ReviewedResearchExperiments,
)
from factorforge.orchestration.research_strategies import ResearchStrategies
from factorforge.retrieval.direction_review import DirectionReview
from factorforge.validation.monthly import MonthlyHACResult

type ResearchResult = (
    ResearchExperiments | ReviewedResearchExperiments | IterativeResearchExperiments
)

_RESULT: TypeAdapter[ResearchResult] = TypeAdapter(
    Annotated[
        ResearchExperiments | ReviewedResearchExperiments | IterativeResearchExperiments,
        Field(discriminator="schema_version"),
    ]
)


class CandidateReport(Contract):
    """An execution verdict is distinct from factor promotion or a statistical finding."""

    source_id: Identifier
    candidate_index: Annotated[int, Field(ge=0, le=2)]
    verdict: Literal[
        "execution_completed", "execution_stopped", "candidate_held", "budget_exhausted"
    ]
    reason: Identifier | None
    terminal_nav_usd: Number | None
    result: ArtifactRef | None
    validation: ArtifactRef | None
    extraction: ArtifactRef
    extracted_direction: Literal["long_high_short_low", "long_low_short_high"] | None
    review: ArtifactRef | None
    reviewed_direction: Literal["long_high_short_low", "long_low_short_high"] | None
    amendment: ArtifactRef | None
    revision_direction: Literal["long_high_short_low", "long_low_short_high"] | None


class ResearchReport(Contract):
    """Report scope and source evidence remain explicit and reproducible without a model call."""

    schema_version: Literal["research-report-v1"] = "research-report-v1"
    scope: Literal["original_fixture_execution_evidence"] = "original_fixture_execution_evidence"
    factor_promotion: Literal["not_assessed"] = "not_assessed"
    run_id: UUID
    source_result: ArtifactRef
    candidates: Annotated[tuple[CandidateReport, ...], Field(max_length=3)]
    verified_artifacts: Annotated[tuple[ArtifactRef, ...], Field(max_length=512)]


def _read(reference: ArtifactRef, artifacts: ArtifactStore) -> bytes:
    """Recheck each consumed object so a provider cannot swap bytes after closure verification."""
    raw = artifacts.get(reference.model_copy(deep=True))
    if type(raw) is not bytes:
        raise ValueError("Artifact provider must return bytes")
    verify_bytes(raw, reference)
    return raw


def build_report(reference: ArtifactRef, artifacts: ArtifactStore) -> ResearchReport:
    """Verify the evidence closure and bind candidate outcomes to actual monthly account paths.

    The caller supplies its canonical scheduler result. Offline byte checks do not grant
    owner access or establish authorship. No model interprets returns or writes verdicts.
    """
    verified = verify_closure(reference, artifacts)
    try:
        raw = _read(reference, artifacts)
        result = _RESULT.validate_json(raw)
        if result.canonical_bytes() != raw:
            raise ValueError("Scheduler result is not canonical")
        execution = result if isinstance(result, ResearchExperiments) else result.execution
        if (
            isinstance(result, ReviewedResearchExperiments)
            and result.plan.execution != execution.plan
        ):
            raise ValueError("Reviewed plan differs from execution plan")
        if (
            isinstance(result, IterativeResearchExperiments)
            and result.plan.execution.execution != execution.plan
        ):
            raise ValueError("Iterative plan differs from execution plan")
        stages = ResearchStrategies.model_validate_json(_read(execution.strategies, artifacts))
        if stages.sources.run_id != execution.run_id or stages.bindings != execution.plan.bindings:
            raise ValueError("Source-stage identity differs from execution")
        sources = stages.sources.selection.sources
        if len(execution.experiments) != len(sources) or len(stages.candidates) != len(sources):
            raise ValueError("Candidate inventory differs from source inventory")
        review_rows = () if isinstance(result, ResearchExperiments) else result.reviews
        review_refs = {row.candidate_index: row.review for row in review_rows}
        amendment_rows = (
            result.amendments if isinstance(result, IterativeResearchExperiments) else ()
        )
        amendment_refs = {row.candidate_index: row.amendment for row in amendment_rows}
        if (
            len(review_refs) != len(review_rows)
            or len(amendment_refs) != len(amendment_rows)
            or not set(review_refs) <= set(range(len(sources)))
            or not set(amendment_refs) <= set(review_refs)
        ):
            raise ValueError("Review/amendment indices are inconsistent")
        rows = []
        for index, row in enumerate(execution.experiments):
            if row.candidate_index != index:
                raise ValueError("Candidate order is inconsistent")
            nav = None
            monthly = None
            expected_draft = stages.candidates[index].draft
            if row.result is not None:
                monthly_raw = _read(row.result, artifacts)
                monthly = MonthlyRun.model_validate_json(monthly_raw)
                if (
                    monthly.canonical_bytes() != monthly_raw
                    or monthly.status != row.status
                    or monthly.failure_code != row.reason
                ):
                    raise ValueError("Monthly outcome differs from scheduler outcome")
                if monthly.status == "completed":
                    if monthly.path is None:
                        raise ValueError("Completed execution has no account path")
                    nav = monthly.path.closes[-1].nav_usd
            elif row.status in {"completed", "failed"}:
                raise ValueError("Executed candidate is missing its result")
            if row.validation is not None:
                diagnostic = MonthlyHACResult.model_validate_json(_read(row.validation, artifacts))
                if (
                    diagnostic.request.result != row.result
                    or diagnostic.request.lags != execution.plan.hac_lags
                    or diagnostic.request.correction != execution.plan.hac_correction
                ):
                    raise ValueError("Validation is not bound to this monthly result and plan")
            extraction = stages.sources.extractions[index]
            review_ref, amendment_ref = review_refs.get(index), amendment_refs.get(index)
            reviewed_direction = revision_direction = None
            if review_ref is not None:
                review = DirectionReview.model_validate_json(_read(review_ref, artifacts))
                if review.observation is not None:
                    reviewed_direction = review.observation.direction
            if amendment_ref is not None:
                amendment = DirectionAmendment.model_validate_json(_read(amendment_ref, artifacts))
                if (
                    amendment.request.original != stages.candidates[index].draft
                    or amend_direction(amendment.request) != amendment
                ):
                    raise ValueError("Amendment is not bound to its original source draft")
                expected_draft = amendment.draft
                if amendment.request.resolution.observation is not None:
                    revision_direction = amendment.request.resolution.observation.direction
            if monthly is not None and (
                expected_draft is None
                or expected_draft.strategy != monthly.request.spec
                or monthly.request.initial_cash_usd != execution.plan.initial_cash_usd
                or monthly.request.evaluated_at != execution.plan.evaluated_at
            ):
                raise ValueError("Monthly command differs from its source draft or plan")
            verdict: Literal[
                "execution_completed", "execution_stopped", "candidate_held", "budget_exhausted"
            ]
            if row.status == "completed":
                verdict = "execution_completed"
            elif row.status == "failed":
                verdict = "execution_stopped"
            elif row.status == "budget_stopped":
                verdict = "budget_exhausted"
            else:
                verdict = "candidate_held"
            rows.append(
                CandidateReport(
                    source_id=sources[index].paper_id,
                    candidate_index=index,
                    verdict=verdict,
                    reason=row.reason,
                    terminal_nav_usd=nav,
                    result=row.result,
                    validation=row.validation,
                    extraction=extraction.record,
                    extracted_direction=extraction.observation.long_short_direction
                    if extraction.observation is not None
                    else None,
                    review=review_ref,
                    reviewed_direction=reviewed_direction,
                    amendment=amendment_ref,
                    revision_direction=revision_direction,
                )
            )
        return ResearchReport(
            run_id=execution.run_id,
            source_result=reference,
            candidates=tuple(rows),
            verified_artifacts=verified,
        )
    except Exception:
        raise ResearchError(
            "REPORT_EVIDENCE_INVALID", "Research report evidence is inconsistent.", 409
        ) from None


def render_report(report: ResearchReport) -> str:
    """Render typed outcomes and numeric facts; source text cannot inject report prose."""
    report = ResearchReport.model_validate(report)
    lines = [
        "# FactorForge research report",
        "",
        f"Run: `{report.run_id}`",
        "",
        "Scope: original integration fixture. "
        "Factor promotion and published-factor reproduction are not assessed.",
        "",
        f"Verified reachable artifacts: {len(report.verified_artifacts)}.",
        "",
        "[Scheduler result](sha256/"
        f"{report.source_result.sha256[:2]}/{report.source_result.sha256})",
        "",
    ]
    for row in report.candidates:
        lines.extend(
            [
                f"## Candidate {row.candidate_index + 1}: {row.source_id}",
                "",
                f"Outcome: {row.verdict.replace('_', ' ')}.",
                "",
            ]
        )
        if row.reason is not None:
            explanations = {
                "DIRECTION_AMENDMENT_REVISION_INVALID": (
                    "The revision did not provide a valid source-cited direction."
                ),
                "DIRECTION_REVIEW_DISAGREEMENT": (
                    "Extraction and source review disagree on which side to buy and short."
                ),
                "DIRECTION_AMENDMENT_DIRECTION_NOT_CONFIRMED": (
                    "The additional reading did not confirm the reviewed direction."
                ),
                "RESEARCH_BUDGET_REJECTED": (
                    "The next operation exceeded the run's remaining allowance."
                ),
            }
            if row.reason in explanations:
                lines.extend([explanations[row.reason], ""])
            lines.extend(["Recorded reason: `" + row.reason + "`", ""])
        for label, direction in (
            ("Extraction", row.extracted_direction),
            ("Source review", row.reviewed_direction),
            ("Revision", row.revision_direction),
        ):
            if direction is not None:
                meaning = (
                    "buy high scores, short low scores"
                    if direction == "long_high_short_low"
                    else "buy low scores, short high scores"
                )
                lines.extend([f"{label}: {meaning}.", ""])
        if row.terminal_nav_usd is not None:
            lines.extend([f"Terminal account NAV: {row.terminal_nav_usd} USD.", ""])
        for label, ref in (
            ("Extraction evidence", row.extraction),
            ("Review evidence", row.review),
            ("Amendment evidence", row.amendment),
            ("Monthly result", row.result),
            ("Validation evidence", row.validation),
        ):
            if ref is not None:
                lines.extend([f"[{label}](sha256/{ref.sha256[:2]}/{ref.sha256})", ""])
    return "\n".join(lines)
