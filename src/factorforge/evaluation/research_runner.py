"""Execute a frozen development research inventory with durable per-case dispatch receipts."""

import argparse
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import BinaryIO
from uuid import uuid4

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.domain.errors import ResearchError
from factorforge.evaluation.research_batch import (
    ResearchSubmissions,
    ResearchSuite,
    Submission,
    _read,
    evaluate_batch,
)
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.command import OPERATOR
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.synthesis_command import (
    _REQUEST,
    QwenSynthesisResearchRequest,
    SynthesisResearchRequest,
    SynthesisResearchResult,
    execute_synthesis_research,
)

Request = SynthesisResearchRequest | QwenSynthesisResearchRequest
Executor = Callable[[Request, str], SynthesisResearchResult]


def _record(journal: BinaryIO, row: dict[str, object]) -> None:
    """Persist each dispatch boundary before the worker can perform external work."""
    row = row | {"recorded_at": datetime.now(UTC).isoformat()}
    journal.write(json.dumps(row, sort_keys=True).encode() + b"\n")
    journal.flush()
    os.fsync(journal.fileno())


def run_research_batch(
    suite: ResearchSuite,
    artifacts: ArtifactStore,
    execute: Executor,
    *,
    journal_path: Path,
    max_reserved_microusd: int,
) -> ResearchSubmissions:
    """Preflight the whole suite before dispatch, retaining errors without reducing its denominator.

    This execution journal is exclusive, not an automatic retry queue. An interrupted
    dispatch requires reconciliation using its recorded idempotency key before another attempt.
    The sum of case budgets is an upper authorization bound, never a measured dollar cost.
    """
    suite = ResearchSuite.model_validate(suite)
    if type(max_reserved_microusd) is not int or not 1 <= max_reserved_microusd <= 4500000000:
        raise ValueError("Batch reservation ceiling is invalid")
    requests = []
    reserved = 0
    for case in suite.cases:
        verify_closure(case.request, artifacts)
        raw = artifacts.get(case.request.model_copy())
        verify_bytes(raw, case.request)
        request = _REQUEST.validate_json(raw)
        if request.canonical_bytes() != raw:
            raise ValueError("Case request must use canonical contract bytes")
        reserved += int(request.brief.max_llm_cost_usd * Decimal(1000000))
        requests.append(request)
    if reserved > max_reserved_microusd:
        raise ValueError("Aggregate case reservations exceed the batch ceiling")
    suite_ref = publish(suite, artifacts)
    batch_id = uuid4().hex
    results = []
    with journal_path.open("xb") as journal:
        _record(
            journal,
            dict(
                event="batch_started",
                batch_id=batch_id,
                suite=suite_ref.model_dump(),
                reserved_microusd=reserved,
                scope="original development research execution",
            ),
        )
        for case, request in zip(suite.cases, requests, strict=True):
            key = f"research-batch:{batch_id}:{request.sha256}"
            _record(
                journal,
                dict(
                    event="case_dispatch",
                    case_id=case.case_id,
                    request=case.request.model_dump(),
                    idempotency_key=key,
                ),
            )
            started = monotonic()
            ref = None
            try:
                result = SynthesisResearchResult.model_validate(execute(request, key))
                ref = publish(result, artifacts)
                if result.request != case.request:
                    raise ValueError("Worker returned a different request")
                verify_closure(ref, artifacts)
                # The saved-result grader independently binds budget/run/brief identities.
                submissions = ResearchSubmissions(
                    suite=suite_ref, results=(Submission(case_id=case.case_id, result=ref),)
                )
                grade = evaluate_batch(suite, submissions, artifacts)
                entry = next(row for row in grade["grades"] if row["case_id"] == case.case_id)
                if entry["evidence_status"] != "verified":
                    raise ValueError("Worker evidence cannot be verified")
            except Exception as error:
                # Never retry an ambiguous worker call or leak provider exception text.
                if ref is not None:
                    results.append(Submission(case_id=case.case_id, result=ref))
                _record(
                    journal,
                    dict(
                        event="case_unsettled",
                        case_id=case.case_id,
                        result=ref.model_dump() if ref is not None else None,
                        code=error.code
                        if isinstance(error, ResearchError)
                        else "BATCH_CASE_UNSETTLED",
                        elapsed_seconds=monotonic() - started,
                    ),
                )
                continue
            results.append(Submission(case_id=case.case_id, result=ref))
            _record(
                journal,
                dict(
                    event="case_recorded",
                    case_id=case.case_id,
                    result=ref.model_dump(),
                    status=result.status,
                    elapsed_seconds=monotonic() - started,
                ),
            )
        submitted = ResearchSubmissions(suite=suite_ref, results=tuple(results))
        submitted_ref = publish(submitted, artifacts)
        _record(
            journal,
            dict(
                event="batch_recorded",
                submissions=submitted_ref.model_dump(),
                total=len(suite.cases),
                recorded=len(results),
            ),
        )
        return submitted


def main() -> None:
    """Use existing PostgreSQL run ownership and worker budgets for each serial research case."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--max-reserved-microusd", type=int, required=True)
    parser.add_argument("--schema", default="factorforge")
    args = parser.parse_args()
    dsn = os.environ.get("RDS_DSN")
    if not dsn:
        raise ResearchError("OPERATOR_DATABASE_REQUIRED", "RDS_DSN is required.", 422)
    suite = ResearchSuite.model_validate_json(_read(args.suite))
    artifacts = LocalArtifactStore(args.artifacts)
    runs = PostgresRunStore(dsn, schema=args.schema)

    def execute(request: Request, key: str) -> SynthesisResearchResult:
        """Batch identity isolates prospective cases from earlier runs of the same input."""
        run = runs.create(request.brief, key, OPERATOR)
        return execute_synthesis_research(runs, run.run_id, OPERATOR, request, artifacts)

    try:
        submitted = run_research_batch(
            suite,
            artifacts,
            execute,
            journal_path=args.journal,
            max_reserved_microusd=args.max_reserved_microusd,
        )
        print(json.dumps(evaluate_batch(suite, submitted, artifacts)))
    finally:
        runs.close()


if __name__ == "__main__":
    main()
