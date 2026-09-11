"""Canonical run-row locks serialize budget reservation before external dispatch."""

from datetime import datetime
from fractions import Fraction
from uuid import UUID

from factorforge.auth.principal import Principal
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.budgets import BudgetLedger, Operation, reserve
from factorforge.orchestration.postgres_runs import PostgresRunStore, request_hash


def reserve_operation(
    store: PostgresRunStore,
    run_id: UUID,
    principal: Principal,
    operation: Operation,
    *,
    at: datetime,
) -> tuple[BudgetLedger, bool]:
    """Commit exactly one reservation before returning permission to a trusted serial worker.

    A crash after commit leaves unresolved work reserved; replay never dispatches again.
    The caller must establish provider execution/cost evidence before reconciliation. This
    function performs no external work and grants no API capability to browser identities.
    """
    principal.require("execute_research")
    with store._connection() as connection, connection.transaction():
        row = store._owned(connection, run_id, principal, lock=True)
        try:
            brief = ResearchBrief.model_validate(row["request_json"])
            if request_hash(brief) != row["request_hash"]:
                raise ValueError("Canonical request identity changed")
            cost = Fraction(brief.max_llm_cost_usd) * 1000000
            if cost.denominator != 1:
                raise ValueError("Nonintegral budget")
            initial = BudgetLedger(
                run_id=run_id,
                request_sha256=row["request_hash"],
                started_at=row["created_at"],
                max_wall_seconds=brief.max_wall_time_s,
                max_cost_microusd=cost.numerator,
                max_experiments=brief.max_experiments,
                max_operations=128,
                operations=(),
            )
            saved = connection.execute(
                "SELECT ledger_json FROM research_budgets WHERE run_id=%s", (run_id,)
            ).fetchone()
            ledger = initial
            if saved is not None:
                raw = saved["ledger_json"]
                if not isinstance(raw, str) or len(raw.encode()) > 131072:
                    raise ValueError("Budget bytes exceed bound")
                ledger = BudgetLedger.model_validate_json(raw)
                if ledger.canonical_bytes().decode() != raw or ledger.model_dump(
                    exclude={"operations"}
                ) != initial.model_dump(exclude={"operations"}):
                    raise ValueError("Budget identity or limits changed")
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ResearchError(
                "RESEARCH_BUDGET_CORRUPT", "The saved research budget cannot be verified.", 409
            ) from None
        ledger, dispatch = reserve(ledger, operation, at=at)
        if dispatch:
            connection.execute(
                "INSERT INTO research_budgets (run_id,ledger_json) VALUES (%s,%s) "
                "ON CONFLICT (run_id) DO UPDATE SET ledger_json=EXCLUDED.ledger_json",
                (run_id, ledger.canonical_bytes().decode()),
            )
            store._inject("before_budget_commit")
    return ledger, dispatch
