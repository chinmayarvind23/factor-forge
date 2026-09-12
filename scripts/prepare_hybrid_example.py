"""Prepare a reproducible original hybrid proposal for the durable research command."""

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.hybrid_fixture import prepare_hybrid_fixture
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.hybrid_command import HybridExperimentRequest


def main() -> None:
    """Publish original inputs and an exclusive request file without dispatching experiments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    hybrid = prepare_hybrid_fixture(
        Path(__file__).resolve().parents[1], LocalArtifactStore(args.artifacts)
    )
    request = HybridExperimentRequest(
        brief=ResearchBrief(idea=hybrid.rationale, max_experiments=1),
        hybrid=hybrid,
        initial_cash_usd=Decimal("1002"),
        evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
    )
    with args.request.open("xb") as output:
        output.write(request.canonical_bytes())
    print(request.sha256)


if __name__ == "__main__":
    main()
