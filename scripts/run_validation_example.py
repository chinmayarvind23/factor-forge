"""Execute and validate the original twelve-return fixture with durable PostgreSQL replay."""

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from factorforge.backtests.monthly import MonthlyRequest
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.data.validation_fixture import prepare_validation_fixture
from factorforge.domain.research_brief import ResearchBrief
from factorforge.factors.hybrid import publish
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.command import OPERATOR
from factorforge.orchestration.monthly_graph import MonthlyExperimentGraph
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.validation.research import ValidationRequest, validate_research


def main() -> None:
    """One stable example identity recovers execution; validation recomputes from saved NAVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--schema", default="factorforge")
    args = parser.parse_args()
    artifacts = LocalArtifactStore(args.artifacts)
    spec = prepare_validation_fixture(Path(__file__).resolve().parents[1], artifacts)
    request = MonthlyRequest(
        spec=spec,
        initial_cash_usd=Decimal("1002"),
        evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
    )
    brief = ResearchBrief(
        idea="Validate the original twelve-return strategy path", max_experiments=1
    )
    runs = PostgresRunStore(os.environ["RDS_DSN"], schema=args.schema)
    try:
        run = runs.create(brief, "validation-example-v1:" + request.sha256, OPERATOR)
        monthly = MonthlyExperimentGraph(runs, run.run_id, OPERATOR, request, artifacts).finish()
        validation = validate_research(
            ValidationRequest(
                result=monthly,
                initial_train_size=3,
                test_size=3,
                hac_lags=1,
                embargo_seconds=86400,
            ),
            artifacts,
        )
        result = publish(validation, artifacts)
        print(
            json.dumps(
                dict(
                    run_id=str(run.run_id),
                    experiment=monthly.model_dump(),
                    validation=result.model_dump(),
                    verified_artifacts=len(verify_closure(result, artifacts)),
                    budget=publish(read_budget(runs, run.run_id, OPERATOR), artifacts).model_dump(),
                )
            )
        )
    finally:
        runs.close()


if __name__ == "__main__":
    main()
