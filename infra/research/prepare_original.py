"""Prepare a saved original research request without calling a model or reading expected results."""

import argparse
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.literature import PaperDocument
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.command import OperatorRequest
from factorforge.orchestration.research_experiments import (
    ExperimentPlan,
    IterativeExperimentPlan,
    ReviewedExperimentPlan,
)
from factorforge.orchestration.research_strategies import ReviewedStrategyBinding
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry


def main() -> None:
    """Capture evaluation time once and refuse to overwrite the request needed for replay."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--direction-review", action="store_true")
    parser.add_argument("--direction-revision", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    artifacts = LocalArtifactStore(args.artifacts)
    fixture = root / "data/backtests/monthly-raw-v1"
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        artifacts.put(
            (fixture / "inputs" / f"{name}.json").read_bytes(), media_type="application/json"
        )
    spec = RawStrategySpec.model_validate_json((fixture / "strategy.json").read_bytes())
    passage = (root / "data/research/original-monthly-v1/source.txt").read_bytes()
    page = artifacts.put(passage, media_type="text/plain")
    source = SourcePacket(
        paper_id="original-monthly-v1",
        source_sha256=hashlib.sha256(passage).hexdigest(),
        selected_strategy="Original score strategy",
        pages=(SourcePage(pdf_page=1, artifact=page),),
    )
    document = PaperDocument(
        paper_id=source.paper_id,
        title="Original score strategy",
        text=passage.decode("utf-8"),
        source_url="https://github.com/chinmayarvind23/factor-forge/blob/master/data/research/original-monthly-v1/source.txt",
        source_sha256=source.source_sha256,
        content_kind="source_passage",
        source_version="original-v1",
    )
    request = OperatorRequest(
        brief=ResearchBrief(
            idea="Investigate the original monthly score strategy",
            max_experiments=1,
            max_wall_time_s=600,
        ),
        plan=ExperimentPlan(
            catalog=LiteratureCatalog(entries=(LiteratureEntry(document=document, source=source),)),
            bindings=(
                ReviewedStrategyBinding(
                    source=source,
                    environment=spec,
                    reviewed_formation_rule="Last session close each month",
                ),
            ),
            initial_cash_usd=Decimal("1002"),
            evaluated_at=datetime.now(UTC),
            max_cost_per_source_microusd=1000000,
            hac_lags=1,
            hac_correction="none",
        ),
    )
    if args.direction_review or args.direction_revision:
        assert isinstance(request.plan, ExperimentPlan)
        request = OperatorRequest(
            brief=request.brief,
            plan=ReviewedExperimentPlan(
                execution=request.plan, max_cost_per_review_microusd=1000000
            ),
        )
    if args.direction_revision:
        assert isinstance(request.plan, ReviewedExperimentPlan)
        request = OperatorRequest(
            brief=request.brief,
            plan=IterativeExperimentPlan(
                execution=request.plan, max_cost_per_revision_microusd=1000000
            ),
        )
    args.request.parent.mkdir(parents=True, exist_ok=True)
    with args.request.open("xb") as destination:
        destination.write(request.canonical_bytes())
    print(request.sha256)


if __name__ == "__main__":
    main()
