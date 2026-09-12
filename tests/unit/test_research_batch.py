"""Batch evaluation retains the full inventory and rejects substituted research evidence."""

from pathlib import Path

import pytest
from test_budgets import ledger
from test_monthly_admission import MemoryStore

from factorforge.data.synthesis_fixture import prepare_synthesis_fixture
from factorforge.evaluation.research_batch import (
    ResearchCase,
    ResearchSubmissions,
    ResearchSuite,
    Submission,
    evaluate_batch,
)
from factorforge.factors.hybrid import publish
from factorforge.orchestration.postgres_runs import request_hash
from factorforge.orchestration.synthesis_command import SynthesisResearchResult


@pytest.mark.parametrize("scenario", ["held", "missing", "corrupt", "wrong_input", "wrong_budget"])
def test_batch_does_not_turn_missing_or_substituted_evidence_into_completion(scenario: str) -> None:
    """Even a valid terminal receipt needs the declared input and matching run budget."""
    store = MemoryStore()
    request = prepare_synthesis_fixture(Path(__file__).resolve().parents[2], store)
    request_ref = publish(request, store)
    budget = ledger(request_sha256=request_hash(request.brief))
    result = SynthesisResearchResult(
        run_id=budget.run_id,
        request=request_ref,
        strategies=None,
        reviews=(),
        synthesis=None,
        hybrid=None,
        status="held",
        reasons=("INSUFFICIENT_REVIEWED_PARENTS",),
        budget=publish(budget, store),
    )
    case = ResearchCase(case_id="original", request=request_ref)
    if scenario == "wrong_input":
        case = case.model_copy(update={"request": store.put(b"{}", media_type="application/json")})
    if scenario == "wrong_budget":
        result = result.model_copy(update={"budget": publish(ledger(), store)})
    root = publish(result, store)
    if scenario == "corrupt":
        store.values[request_ref.sha256] = b"{}"
    suite = ResearchSuite(cases=(case,))
    submissions = ResearchSubmissions(
        suite=publish(suite, store),
        results=() if scenario == "missing" else (Submission(case_id="original", result=root),),
    )
    score = evaluate_batch(suite, submissions, store)
    assert score["total"] == 1 and score["criteria_passes"] == 0
    assert score["grades"][0]["evidence_status"] == (
        "verified" if scenario == "held" else "missing" if scenario == "missing" else "invalid"
    )
    assert score == evaluate_batch(suite, submissions, store)


@pytest.mark.parametrize("scenario", ["duplicate_input", "duplicate_result", "unknown", "suite"])
def test_batch_rejects_denominator_changes(scenario: str) -> None:
    """Duplicate aliases and mismatched manifests cannot alter the declared case inventory."""
    store = MemoryStore()
    first = store.put(b"first")
    second = store.put(b"second")
    if scenario == "duplicate_input":
        with pytest.raises(ValueError, match="repeats"):
            ResearchSuite(
                cases=(
                    ResearchCase(case_id="one", request=first),
                    ResearchCase(case_id="two", request=first),
                )
            )
        return
    suite = ResearchSuite(
        cases=(
            ResearchCase(case_id="one", request=first),
            ResearchCase(case_id="two", request=second),
        )
    )
    submitted = ResearchSubmissions(
        suite=first if scenario == "suite" else publish(suite, store),
        results=(
            Submission(case_id="unknown" if scenario == "unknown" else "one", result=first),
            Submission(case_id="two", result=first if scenario == "duplicate_result" else second),
        ),
    )
    with pytest.raises(ValueError):
        evaluate_batch(suite, submitted, store)
