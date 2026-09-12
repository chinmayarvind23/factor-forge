"""Durable research-to-report execution with canonical receipts and owner-scoped memory."""

import hashlib
from typing import Any, TypedDict, cast
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore, reference
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.factors import Contract
from factorforge.domain.research_brief import ResearchBrief
from factorforge.lineage.closure import verify_closure
from factorforge.orchestration.normalization_graph import safe_checkpoint
from factorforge.orchestration.operator_request import OperatorRequest
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.report_export import ResearchCompletion, export_report
from factorforge.orchestration.research_experiments import ResearchExperiments, research_experiments
from factorforge.orchestration.research_report import _RESULT
from factorforge.orchestration.research_strategies import _publish


class WorkflowState(TypedDict):
    """Full request and owner bindings survive restart; results point to immutable evidence."""

    run_id: str  # Owner-bearing canonical run.
    issuer: str  # Captured outside checkpoint data.
    subject: str  # Captured outside checkpoint data.
    request: str  # Full canonical request, including model policy and evaluation clock.
    result: str  # Canonical ArtifactRef JSON, empty until research publication.
    completion: str  # Canonical completion reference, empty until report publication.


class MemoryHit(Contract):
    """A saved research outcome locator is evidence to inspect, not a promotion decision."""

    run_id: UUID
    idea: str
    completion: ArtifactRef


def search_memory(
    runs: PostgresRunStore, principal: Principal, query: str, *, limit: int = 10
) -> tuple[MemoryHit, ...]:
    """Bounded literal idea search returns only the caller's completed workflow receipts."""
    principal.require("execute_research")
    if len(query) > 256 or type(limit) is not int or not 1 <= limit <= 50:
        raise ResearchError("MEMORY_QUERY_INVALID", "Use a bounded memory query and limit.", 422)
    with runs._connection() as connection:
        rows = connection.execute(
            "SELECT r.run_id, r.request_json->>'idea' AS idea, w.completion_ref "
            "FROM research_workflows w JOIN research_runs r USING (run_id) "
            "WHERE r.owner_issuer=%s AND r.owner_subject=%s AND w.remembered "
            "AND strpos(lower(r.request_json->>'idea'), lower(%s))>0 "
            "ORDER BY r.created_at DESC, r.run_id, w.request_sha256 LIMIT %s",
            (principal.issuer, principal.subject, query, limit),
        ).fetchall()
    return tuple(
        MemoryHit(
            run_id=row["run_id"],
            idea=row["idea"],
            completion=ArtifactRef.model_validate_json(row["completion_ref"]),
        )
        for row in rows
    )


def _conflict() -> ResearchError:
    """Keep persisted-state diagnostics stable and free of private research contents."""
    return ResearchError("WORKFLOW_CONFLICT", "The saved research workflow is inconsistent.", 409)


class ResearchWorkflow:
    """Compose existing bounded research stages, report export and reusable outcome memory.

    PostgreSQL receipts are authoritative; LangGraph checkpoints select the next stage.
    Existing operation reservations still own dispatch and uncertainty after provider crashes.
    No new model policy, retry, quant threshold or benchmark definition is introduced.
    """

    def __init__(
        self,
        runs: PostgresRunStore,
        run_id: UUID,
        principal: Principal,
        request: OperatorRequest,
        artifacts: LocalArtifactStore,
    ) -> None:
        """Bind identity and immutable inputs outside checkpoint-controlled fields."""
        self.runs, self.run_id, self.principal = runs, run_id, principal
        self.request = OperatorRequest.model_validate(request)
        self.artifacts = artifacts
        self.request_ref = reference(self.request.canonical_bytes(), "application/json", 4 * 2**20)
        self.initial: WorkflowState = dict(
            run_id=str(run_id),
            issuer=principal.issuer,
            subject=principal.subject,
            request=self.request.canonical_bytes().decode(),
            result="",
            completion="",
        )
        self.thread = str(uuid5(run_id, "research-workflow-v1:" + self.request.sha256))
        self.saver = runs._graph.saver
        builder = StateGraph(WorkflowState)
        builder.add_node("research", self._research)
        builder.add_node("report", self._report)
        builder.add_node("remember", self._remember)
        builder.add_edge(START, "research")
        builder.add_edge("research", "report")
        builder.add_edge("report", "remember")
        builder.add_edge("remember", END)
        self.graph = builder.compile(checkpointer=self.saver)

    def _validate(self, state: object) -> WorkflowState:
        """Reject owner/request substitutions before any evidence access or execution."""
        if (
            not isinstance(state, dict)
            or set(state) != set(self.initial)
            or not all(isinstance(value, str) for value in state.values())
            or any(
                state[key] != self.initial[key]
                for key in ("run_id", "issuer", "subject", "request")
            )
        ):
            raise _conflict()
        return cast(WorkflowState, state)

    def _row(self) -> dict[str, Any] | None:
        """Canonical receipt lookup is always owner-scoped, including replay."""
        with self.runs._connection() as connection:
            self.runs._owned(connection, self.run_id, self.principal)
            row = connection.execute(
                "SELECT * FROM research_workflows WHERE run_id=%s AND request_sha256=%s",
                (self.run_id, self.request.sha256),
            ).fetchone()
        if row is not None and row["request_ref"] != self.request_ref.model_dump_json():
            raise _conflict()
        return row

    def _research(self, state: WorkflowState) -> dict[str, str]:
        """Recover an entire recorded research stage without reentering its scheduler."""
        self._validate(state)
        saved = self._row()
        if saved is not None:
            return {"result": saved["result_ref"]}
        _publish(self.request, self.artifacts)
        result = research_experiments(
            self.runs, self.run_id, self.principal, self.request.plan, self.artifacts
        )
        result_ref = _publish(result, self.artifacts)
        budget_ref = _publish(read_budget(self.runs, self.run_id, self.principal), self.artifacts)
        with self.runs._connection() as connection, connection.transaction():
            self.runs._owned(connection, self.run_id, self.principal)
            connection.execute(
                "INSERT INTO research_workflows "
                "(run_id,request_sha256,request_ref,result_ref,budget_ref) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (
                    self.run_id,
                    self.request.sha256,
                    self.request_ref.model_dump_json(),
                    result_ref.model_dump_json(),
                    budget_ref.model_dump_json(),
                ),
            )
        saved = self._row()
        if (
            saved is None
            or saved["result_ref"] != result_ref.model_dump_json()
            or saved["budget_ref"] != budget_ref.model_dump_json()
        ):
            raise _conflict()
        self.runs._inject("after_workflow_research_receipt")
        return {"result": saved["result_ref"]}

    def _completion(self, state: WorkflowState) -> ArtifactRef:
        """Verify result, plan, budget and report against canonical rows before completion."""
        self._validate(state)
        saved = self._row()
        if saved is None or state["result"] != saved["result_ref"]:
            raise _conflict()
        result_ref = ArtifactRef.model_validate_json(saved["result_ref"])
        raw = self.artifacts.get(result_ref)
        result = _RESULT.validate_json(raw)
        execution = result if isinstance(result, ResearchExperiments) else result.execution
        if (
            result.canonical_bytes() != raw
            or execution.run_id != self.run_id
            or result.plan != self.request.plan
        ):
            raise _conflict()
        budget_ref = ArtifactRef.model_validate_json(saved["budget_ref"])
        if (
            self.artifacts.get(budget_ref)
            != read_budget(self.runs, self.run_id, self.principal).canonical_bytes()
        ):
            raise _conflict()
        exported, _ = export_report(result_ref, self.artifacts)
        completion = _publish(
            ResearchCompletion(
                run_id=self.run_id,
                request=self.request_ref,
                result=result_ref,
                budget=budget_ref,
                report=exported.report,
                markdown=exported.markdown,
            ),
            self.artifacts,
        )
        verify_closure(completion, self.artifacts)
        return completion

    def _report(self, state: WorkflowState) -> dict[str, str]:
        """Report retries regenerate identical artifacts and preserve conflicting user exports."""
        self._validate(state)
        self.runs._inject("before_workflow_report")
        completion = self._completion(state).model_dump_json()
        with self.runs._connection() as connection, connection.transaction():
            self.runs._owned(connection, self.run_id, self.principal)
            connection.execute(
                "UPDATE research_workflows SET completion_ref=%s "
                "WHERE run_id=%s AND request_sha256=%s AND completion_ref IS NULL",
                (completion, self.run_id, self.request.sha256),
            )
        saved = self._row()
        if saved is None or saved["completion_ref"] != completion:
            raise _conflict()
        return {"completion": completion}

    def _remember(self, state: WorkflowState) -> dict[str, str]:
        """Publish both successful and held outcomes to owner-scoped reusable research memory."""
        self._validate(state)
        saved = self._row()
        if (
            saved is None
            or saved["completion_ref"] != state["completion"]
            or saved["result_ref"] != state["result"]
        ):
            raise _conflict()
        if self._completion(state).model_dump_json() != state["completion"]:
            raise _conflict()
        self.runs._inject("before_workflow_memory")
        with self.runs._connection() as connection, connection.transaction():
            self.runs._owned(connection, self.run_id, self.principal)
            connection.execute(
                "UPDATE research_workflows SET remembered=true "
                "WHERE run_id=%s AND request_sha256=%s",
                (self.run_id, self.request.sha256),
            )
        return {}

    @safe_checkpoint
    def finish(self) -> ArtifactRef:
        """Serialize workflow writers; terminal replay verifies evidence without model dispatch."""
        self.principal.require("execute_research")
        config: RunnableConfig = {"configurable": {"thread_id": self.thread}, "recursion_limit": 6}
        with self.runs._connection() as connection, connection.transaction():
            owner = self.runs._owned(connection, self.run_id, self.principal)
            if ResearchBrief.model_validate(owner["request_json"]) != self.request.brief:
                raise _conflict()
            key = int.from_bytes(
                hashlib.sha256(self.thread.encode()).digest()[:8], "big", signed=True
            )
            lock = connection.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS locked", (key,)
            ).fetchone()
            if lock is None or not lock["locked"]:
                raise ResearchError(
                    "RESEARCH_BUSY", "The research workflow already has a worker.", 409
                )
            if self.saver.get_tuple(config) is None:
                self.graph.invoke(self.initial, config, durability="sync")
            else:
                snapshot = self.graph.get_state(config)
                self._validate(snapshot.values)
                if snapshot.next:
                    self.graph.invoke(None, config, durability="sync")
            final = self.graph.get_state(config)
            state = self._validate(final.values)
            completion = self._completion(state)
            saved = self._row()
            if (
                final.next
                or saved is None
                or not saved["remembered"]
                or state["completion"] != completion.model_dump_json()
                or saved["completion_ref"] != state["completion"]
            ):
                raise _conflict()
            return completion
