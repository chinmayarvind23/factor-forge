"""Run explicitly proposed multi-source hybrids through existing durable experiment gates."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import UUID

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRequest, MonthlyRun
from factorforge.data.artifacts import LocalArtifactStore, reference
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.performance import Instant, Positive
from factorforge.domain.research_brief import ResearchBrief
from factorforge.factors.hybrid import HybridRequest, compile_hybrid, publish
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.command import OPERATOR
from factorforge.orchestration.monthly_graph import MonthlyExperimentGraph
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore


class HybridExperimentRequest(Contract):
    """Bind the blend, capital and captured evaluation clock to one immutable run request."""

    schema_version: Literal["hybrid-experiment-request-v1"] = "hybrid-experiment-request-v1"
    brief: ResearchBrief
    hybrid: HybridRequest
    initial_cash_usd: Positive
    evaluated_at: Instant


class HybridExecution(Contract):
    """The proposal, actual execution and report remain linked even when a blend is held."""

    schema_version: Literal["hybrid-experiment-result-v1"] = "hybrid-experiment-result-v1"
    run_id: UUID
    request: ArtifactRef
    draft: ArtifactRef
    experiment: ArtifactRef | None
    status: Literal["completed", "failed", "held", "budget_stopped"]
    reasons: tuple[str, ...]
    budget: ArtifactRef
    report: ArtifactRef


def execute_hybrid(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    request: HybridExperimentRequest,
    artifacts: LocalArtifactStore,
) -> HybridExecution:
    """Compile and execute under existing ownership, operation budgets and replay semantics."""
    principal.require("execute_research")
    request = HybridExperimentRequest.model_validate(request)
    with runs._connection() as connection:
        owner = runs._owned(connection, run_id, principal)
        if ResearchBrief.model_validate(owner["request_json"]) != request.brief:
            raise ResearchError("HYBRID_REQUEST_CONFLICT", "The run brief differs.", 409)
    request_ref = publish(request, artifacts)
    draft = compile_hybrid(request.hybrid, artifacts)
    draft_ref = publish(draft, artifacts)
    experiment = None
    status: Literal["completed", "failed", "held", "budget_stopped"] = "held"
    reasons = draft.reasons
    terminal = None
    if draft.strategy is not None:
        command = MonthlyRequest(
            spec=draft.strategy,
            initial_cash_usd=request.initial_cash_usd,
            evaluated_at=request.evaluated_at,
        )
        try:
            experiment = MonthlyExperimentGraph(
                runs, run_id, principal, command, artifacts
            ).finish()
        except ResearchError as error:
            if error.code != "RESEARCH_BUDGET_REJECTED":
                raise
            status, reasons = "budget_stopped", (error.code,)
        else:
            actual = MonthlyRun.model_validate_json(artifacts.get(experiment))
            if actual.request != command:
                raise ResearchError("HYBRID_RESULT_CONFLICT", "The execution request differs.", 409)
            status = actual.status
            reasons = (actual.failure_code,) if actual.failure_code is not None else ()
            if actual.performance is not None:
                terminal = str(actual.performance.terminal_nav_usd)
    report = (
        "# Hybrid research execution\n\n"
        f"Status: {status}\n\n"
        f"Components: {len(request.hybrid.components)}\n\n"
        "Policy: positive rational weights, aligned long-high direction, caller-declared "
        "comparable raw score scales. No fitted standardization or weight optimization.\n\n"
        f"Terminal account NAV: {terminal if terminal is not None else 'unavailable'} USD.\n\n"
        f"Decision codes: {', '.join(reasons) if reasons else 'execution completed'}\n\n"
        f"Draft SHA-256: {draft_ref.sha256}\n\n"
        "Scope: execution evidence. Factor promotion and published-paper reproduction "
        "are not assessed by this command.\n"
    ).encode()
    report_ref = reference(report, "text/markdown", 2**20)
    if artifacts.put(report, media_type="text/markdown") != report_ref:
        raise ResearchError("HYBRID_EVIDENCE_INVALID", "Report publication differs.", 409)
    result = HybridExecution(
        run_id=run_id,
        request=request_ref,
        draft=draft_ref,
        experiment=experiment,
        status=status,
        reasons=reasons,
        budget=publish(read_budget(runs, run_id, principal), artifacts),
        report=report_ref,
    )
    verify_closure(publish(result, artifacts), artifacts)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Expose the complete local hybrid path without adding a network service or model charge."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--schema", default="factorforge")
    args = parser.parse_args(argv)
    try:
        with args.request.open("rb") as source:
            raw = source.read(4 * 2**20 + 1)
        if len(raw) > 4 * 2**20:
            raise ValueError("Request exceeds limit")
        request = HybridExperimentRequest.model_validate_json(raw)
        dsn = os.environ.get("RDS_DSN")
        if not dsn:
            raise ResearchError("OPERATOR_DATABASE_REQUIRED", "RDS_DSN is required.", 422)
        artifacts = LocalArtifactStore(args.artifacts)
        runs = PostgresRunStore(dsn, schema=args.schema)
        try:
            run = runs.create(request.brief, "hybrid:" + request.sha256, OPERATOR)
            result = execute_hybrid(runs, run.run_id, OPERATOR, request, artifacts)
            print(
                json.dumps(
                    {
                        "run_id": str(run.run_id),
                        "result": publish(result, artifacts).model_dump(mode="json"),
                        "status": result.status,
                    }
                )
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
                        "code": "HYBRID_EXECUTION_STOPPED",
                        "message": "Retain the request for reconciliation.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
