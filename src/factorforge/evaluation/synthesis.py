"""Read-only grading of the frozen original source-to-hybrid engineering case."""

import argparse
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from factorforge.backtests.monthly import MonthlyRun
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.budgets import BudgetLedger
from factorforge.orchestration.hybrid_command import HybridExecution
from factorforge.orchestration.research_strategies import ResearchStrategies
from factorforge.orchestration.synthesis_command import SynthesisResearchResult
from factorforge.retrieval.synthesis import SynthesisResult


def grade_synthesis(root: ArtifactRef, artifacts: ArtifactStore) -> dict[str, Any]:
    """Grade saved bytes without model calls, output repair or dispatch permission.

    Criteria implement synthesis-original-v1, an original development case. Artifact
    integrity and ledger counts do not prove paper replication or economic validity.
    """
    refs = verify_closure(root, artifacts)
    result = SynthesisResearchResult.model_validate_json(artifacts.get(root))
    ledger = BudgetLedger.model_validate_json(artifacts.get(result.budget))
    counts = {
        kind: sum(row.operation.kind == kind for row in ledger.operations)
        for kind in ("llm", "experiment")
    }
    checks = dict(
        completed=result.status == "completed",
        source_formulas=False,
        source_directions=False,
        compiled_parents=False,
        weights=False,
        literal_citations=False,
        terminal_nav=False,
        initial_cash=False,
        operation_limits=counts["llm"] <= 5 and counts["experiment"] <= 1,
        operations_settled=all(row.observation is not None for row in ledger.operations),
    )
    sources = None
    candidates = []
    if result.strategies is not None:
        strategies = ResearchStrategies.model_validate_json(artifacts.get(result.strategies))
        sources = strategies.sources
        rows = list(zip(sources.selection.sources, sources.extractions, strict=True))
        expected = {"original-score": "score", "original-quality": "quality"}
        checks["source_formulas"] = {
            source.paper_id: extraction.observation.formula
            for source, extraction in rows
            if extraction.observation is not None
        } == expected
        checks["source_directions"] = len(rows) == 2 and all(
            extraction.observation is not None
            and extraction.observation.long_short_direction == "long_high_short_low"
            for _, extraction in rows
        )
        checks["compiled_parents"] = len(strategies.candidates) == 2 and all(
            row.status == "compiled" for row in strategies.candidates
        )
        candidates = [
            dict(
                source=source.paper_id,
                status=candidate.status,
                reasons=list(candidate.draft.reasons) if candidate.draft is not None else [],
                observation=extraction.observation.model_dump(mode="json")
                if extraction.observation is not None
                else None,
            )
            for (source, extraction), candidate in zip(rows, strategies.candidates, strict=True)
        ]
    if result.synthesis is not None and sources is not None:
        synthesis = SynthesisResult.model_validate_json(artifacts.get(result.synthesis))
        if synthesis.status == "proposed" and synthesis.observation is not None:
            allocations = synthesis.observation.allocations
            checks["weights"] = {
                row.paper_id: Fraction(row.numerator, row.denominator) for row in allocations
            } == {"original-score": Fraction(3, 4), "original-quality": Fraction(1, 4)}
            pages = {
                (source.paper_id, page.pdf_page): " ".join(
                    artifacts.get(page.artifact).decode("utf-8").split()
                )
                for source in sources.selection.sources
                for page in source.pages
            }
            checks["literal_citations"] = len(allocations) == 2 and all(
                bool(row.quote.strip())
                and " ".join(row.quote.split()) in pages.get((row.paper_id, row.pdf_page), "")
                for row in allocations
            )
    nav = None
    if result.hybrid is not None:
        hybrid = HybridExecution.model_validate_json(artifacts.get(result.hybrid))
        if hybrid.experiment is not None:
            monthly = MonthlyRun.model_validate_json(artifacts.get(hybrid.experiment))
            checks["initial_cash"] = monthly.request.initial_cash_usd == Decimal("1002")
            if monthly.performance is not None:
                nav = str(monthly.performance.terminal_nav_usd)
                checks["terminal_nav"] = Decimal(nav) == Decimal("1057.98")
    return dict(
        suite_id="synthesis-original-v1",
        scope="Original engineering development case; not published-factor accuracy",
        result=root.model_dump(mode="json"),
        request=result.request.model_dump(mode="json"),
        status=result.status,
        checks=checks,
        passed=all(checks.values()),
        verified_artifacts=len(refs),
        operations=counts,
        terminal_nav_usd=nav,
        candidates=candidates,
    )


def main() -> None:
    """Accept the retained CLI result envelope and produce an exclusively created scorecard."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.receipt.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Receipt exceeds size limit")
    receipt = json.loads(raw)
    if "stdout" in receipt:
        receipt = json.loads(receipt["stdout"])
    grade = grade_synthesis(
        ArtifactRef.model_validate(receipt["result"]), LocalArtifactStore(args.artifacts)
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(grade, output, indent=2)
    print(json.dumps({key: value for key, value in grade.items() if key != "candidates"}))


if __name__ == "__main__":
    main()
