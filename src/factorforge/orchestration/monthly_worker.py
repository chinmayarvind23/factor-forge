"""Trusted monthly execution connects canonical budgets to retained backtest artifacts."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid5

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRequest, MonthlyRun, run_monthly
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.budgets import Operation
from factorforge.orchestration.postgres_budgets import reserve_operation, settle_operation
from factorforge.orchestration.postgres_runs import PostgresRunStore


def execute_monthly_operation(
    runs: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    request: MonthlyRequest,
    artifacts: ArtifactStore,
) -> MonthlyRun:
    """Execute one immutable monthly command or recover its already settled result.

    The graph must retain the exact request, including its evaluation clock, across retries.
    UUID derivation is server-owned and distinct per canonical run. No graph checkpoint or
    caller Boolean grants dispatch: only the committed owner-bound reservation does.
    """
    principal.require("execute_research")
    request = MonthlyRequest.model_validate(request)
    operation = Operation(
        operation_id=uuid5(run_id, "monthly-worker-v1:" + request.sha256),
        kind="experiment",
        request_sha256=request.sha256,
        max_cost_microusd=0,
    )
    ledger, dispatch = reserve_operation(runs, run_id, principal, operation, at=datetime.now(UTC))
    if not dispatch:
        reservation = next(row for row in ledger.operations if row.operation == operation)
        if reservation.observation is None:
            raise ResearchError(
                "RESEARCH_OPERATION_UNRESOLVED", "The recorded operation needs reconciliation.", 409
            )
        return _recover(artifacts, reservation.observation.result, request)
    runs._inject("after_monthly_reservation")
    result = run_monthly(
        request.spec,
        artifacts,
        initial_cash_usd=request.initial_cash_usd,
        evaluated_at=request.evaluated_at,
    )
    raw = result.canonical_bytes()
    expected = ArtifactRef(
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json"
    )
    if len(raw) > 2**20 or result.request != request:
        raise ResearchError(
            "RESEARCH_RESULT_INVALID", "The operation result cannot be verified.", 409
        )
    published = artifacts.put(raw, media_type="application/json")
    if published != expected:
        raise ResearchError(
            "RESEARCH_RESULT_INVALID", "The operation result cannot be verified.", 409
        )
    runs._inject("before_monthly_settlement")
    settle_operation(
        runs,
        run_id,
        principal,
        operation.operation_id,
        result=expected,
        artifacts=artifacts,
        actual_cost_microusd=0,
        at=datetime.now(UTC),
    )
    return result


def _recover(artifacts: ArtifactStore, ref: ArtifactRef, request: MonthlyRequest) -> MonthlyRun:
    """Reload exact retained bytes and bind the parsed result to the immutable command."""
    try:
        ref = ArtifactRef.model_validate(ref)
        if ref.size_bytes > 2**20 or ref.media_type != "application/json":
            raise ValueError("Unsupported result envelope")
        raw = artifacts.get(ref.model_copy(deep=True))
        if (
            type(raw) is not bytes
            or len(raw) != ref.size_bytes
            or hashlib.sha256(raw).hexdigest() != ref.sha256
        ):
            raise ValueError("Result byte mismatch")
        result = MonthlyRun.model_validate_json(raw)
        if result.canonical_bytes() != raw or result.request != request:
            raise ValueError("Result request mismatch")
        return result
    except Exception:
        raise ResearchError(
            "RESEARCH_RESULT_INVALID", "The operation result cannot be verified.", 409
        ) from None
