"""Aggregate saved research attempts without dropping missing or invalid evidence."""

import argparse
import json
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract, Identifier
from factorforge.evaluation.synthesis import grade_synthesis
from factorforge.lineage.closure import verify_closure
from factorforge.lineage.trajectories import _Snapshot
from factorforge.orchestration.budgets import BudgetLedger
from factorforge.orchestration.postgres_runs import request_hash
from factorforge.orchestration.synthesis_command import _REQUEST, SynthesisResearchResult


class ResearchCase(Contract):
    """Input identity belongs to the case inventory, independently of submitted output."""

    case_id: Identifier
    request: ArtifactRef


class ResearchSuite(Contract):
    """This original-case rubric measures development attempts, never release autonomy."""

    schema_version: Literal["research-development-suite-v1"] = "research-development-suite-v1"
    rubric: Literal["synthesis-original-v1"] = "synthesis-original-v1"
    cases: Annotated[tuple[ResearchCase, ...], Field(min_length=1, max_length=45)]

    @model_validator(mode="after")
    def distinct_inputs(self) -> Self:
        """Aliases for the same input cannot inflate a case denominator."""
        if len({row.case_id for row in self.cases}) != len(self.cases) or len(
            {row.request.sha256 for row in self.cases}
        ) != len(self.cases):
            raise ValueError("Suite repeats a case or input")
        return self


class Submission(Contract):
    """Absent outputs remain explicit cases instead of disappearing from the denominator."""

    case_id: Identifier
    result: ArtifactRef


class ResearchSubmissions(Contract):
    """A batch declares exactly which inventory it submits results against."""

    suite: ArtifactRef
    results: Annotated[tuple[Submission, ...], Field(max_length=45)]


def evaluate_batch(
    suite: ResearchSuite, submitted: ResearchSubmissions, artifacts: ArtifactStore
) -> dict[str, Any]:
    """Regrade immutable bytes; never accept cached pass flags or invoke research workers.

    A snapshot prevents an artifact source from changing between closure validation and
    grading. Per-case evidence errors are retained; inventory errors reject the batch.
    Saved evidence alone cannot establish absence of human intervention during a run.
    """
    suite = ResearchSuite.model_validate(suite)
    submitted = ResearchSubmissions.model_validate(submitted)
    expected = ArtifactRef(
        sha256=suite.sha256, size_bytes=len(suite.canonical_bytes()), media_type="application/json"
    )
    if submitted.suite != expected:
        raise ValueError("Submission does not identify this suite")
    outputs = {row.case_id: row.result for row in submitted.results}
    if len(outputs) != len(submitted.results) or not outputs.keys() <= {
        row.case_id for row in suite.cases
    }:
        raise ValueError("Submission repeats or introduces a case")
    if len({row.result.sha256 for row in submitted.results}) != len(submitted.results):
        raise ValueError("Submission reuses a result")
    grades: list[dict[str, Any]] = []
    for case in suite.cases:
        root = outputs.get(case.case_id)
        row: dict[str, Any] = dict(
            case_id=case.case_id,
            request=case.request.model_dump(mode="json"),
            result=root.model_dump(mode="json") if root else None,
            evidence_status="missing",
            criteria_pass=False,
            grade=None,
        )
        if root is not None:
            try:
                snapshot = _Snapshot(artifacts)
                verify_closure(root, snapshot)
                result = SynthesisResearchResult.model_validate_json(snapshot.get(root))
                if result.request != case.request:
                    raise ValueError("Result belongs to a different input")
                request = _REQUEST.validate_json(snapshot.get(case.request))
                ledger = BudgetLedger.model_validate_json(snapshot.get(result.budget))
                if ledger.run_id != result.run_id or ledger.request_sha256 != request_hash(
                    request.brief
                ):
                    raise ValueError("Result and budget identities differ")
                grade = grade_synthesis(root, snapshot)
                row.update(evidence_status="verified", criteria_pass=grade["passed"], grade=grade)
            except (ResearchError, ValueError, OSError, KeyError):
                # Keep private source text and filesystem details out of error scorecards.
                row.update(evidence_status="invalid")
        grades.append(row)
    return dict(
        schema_version="research-development-evaluation-v1",
        suite=expected.model_dump(mode="json"),
        rubric=suite.rubric,
        scope="Saved original development attempts; not release autonomy or factor reproduction",
        total=len(grades),
        criteria_passes=sum(row["criteria_pass"] for row in grades),
        missing=sum(row["evidence_status"] == "missing" for row in grades),
        invalid=sum(row["evidence_status"] == "invalid" for row in grades),
        grades=grades,
    )


def _read(path: Path) -> bytes:
    """Bound local manifest reads before parsing operator-supplied JSON."""
    with path.open("rb") as source:
        raw = source.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Batch manifest exceeds limit")
    return raw


def main() -> None:
    """Create an exclusive local scorecard with no provider or database connection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--submissions", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suite = ResearchSuite.model_validate_json(_read(args.suite))
    submissions = ResearchSubmissions.model_validate_json(_read(args.submissions))
    result = evaluate_batch(suite, submissions, LocalArtifactStore(args.artifacts))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key != "grades"}))


if __name__ == "__main__":
    main()
