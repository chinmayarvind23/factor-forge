"""Trusted local operator entrypoint for the implemented PostgreSQL research pipeline."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.research_experiments import ExperimentPlan, research_experiments
from factorforge.orchestration.research_strategies import _publish

OPERATOR = Principal(
    "factorforge-operator",
    "local-worker",
    frozenset({"create_run", "read_own_run", "execute_research"}),
)


class OperatorRequest(Contract):
    """A complete retained brief and plan define the operator's stable idempotency key."""

    brief: ResearchBrief
    plan: ExperimentPlan


def _request(path: Path) -> OperatorRequest:
    """Bound local request reads and translate schema details before connection initialization."""
    try:
        with path.open("rb") as source:
            raw = source.read(4 * 2**20 + 1)
        if len(raw) > 4 * 2**20:
            raise ValueError("Request exceeds limit")
        return OperatorRequest.model_validate_json(raw)
    except (OSError, ValueError, ValidationError):
        raise ResearchError(
            "OPERATOR_REQUEST_INVALID", "The research request is invalid or unavailable.", 422
        ) from None


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a trusted saved plan; stdout records run and artifact identities for restart.

    Database credentials are read only from RDS_DSN. The fixed operator identity is for
    a trusted local process with direct database access, never an HTTP authentication path.
    """
    parser = argparse.ArgumentParser(prog="factorforge-research")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--schema", default="factorforge")
    args = parser.parse_args(argv)
    try:
        request = _request(args.request)
        dsn = os.environ.get("RDS_DSN")
        if not dsn:
            raise ResearchError("OPERATOR_DATABASE_REQUIRED", "RDS_DSN is required.", 422)
        artifacts = LocalArtifactStore(args.artifacts)
        runs = PostgresRunStore(dsn, schema=args.schema)
        try:
            run = runs.create(request.brief, "operator:" + request.sha256, OPERATOR)
            request_ref = _publish(request, artifacts)
            print(
                json.dumps(
                    {"run_id": str(run.run_id), "request": request_ref.model_dump(mode="json")}
                ),
                flush=True,
            )
            result = research_experiments(runs, run.run_id, OPERATOR, request.plan, artifacts)
            result_ref = _publish(result, artifacts)
            print(
                json.dumps(
                    {"run_id": str(run.run_id), "result": result_ref.model_dump(mode="json")}
                ),
                flush=True,
            )
        finally:
            runs.close()
    except ResearchError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}), file=sys.stderr
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "OPERATOR_EXECUTION_FAILED",
                        "message": "Execution stopped; retain the request for reconciliation.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
