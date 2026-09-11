"""Persisted experiment subgraph delegates dispatch authority to canonical operation budgets."""

import hashlib
from typing import TypedDict, cast
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRequest
from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.orchestration.monthly_worker import (
    execute_monthly_operation,
    recover_monthly_operation,
)
from factorforge.orchestration.normalization_graph import safe_checkpoint
from factorforge.orchestration.postgres_runs import PostgresRunStore


class MonthlyState(TypedDict):
    """Full command and owner identity survive checkpoints; artifacts hold the result closure."""

    run_id: str  # Canonical owner-bearing research run.
    owner_issuer: str  # Verified issuer, never supplied by a checkpoint as authority.
    owner_subject: str  # Verified subject paired with issuer.
    graph_version: str  # Distinguishes this experiment graph from normalization.
    request_json: str  # Exact canonical monthly command including captured evaluation clock.
    result_json: str  # Full retained executor output, empty before execution.
    manifest_sha256: str  # Published terminal artifact identity, empty until verified publication.


class MonthlyExperimentGraph:
    """One immutable owner/command binding uses synchronous PostgreSQL checkpoints.

    This subgraph executes an already supplied strategy. Literature selection and hypothesis
    creation are upstream research stages, not implied by completing this experiment graph.
    """

    def __init__(
        self,
        runs: PostgresRunStore,
        run_id: UUID,
        principal: Principal,
        request: MonthlyRequest,
        artifacts: ArtifactStore,
    ) -> None:
        """Capture trusted invocation identity outside checkpoint-controlled state."""
        self.runs, self.run_id, self.principal, self.artifacts = runs, run_id, principal, artifacts
        self.request = MonthlyRequest.model_validate(request)
        self.initial: MonthlyState = dict(
            run_id=str(run_id),
            owner_issuer=principal.issuer,
            owner_subject=principal.subject,
            graph_version="monthly-experiment-graph-v1",
            request_json=self.request.canonical_bytes().decode(),
            result_json="",
            manifest_sha256="",
        )
        self.thread = str(uuid5(run_id, "monthly-experiment-graph-v1:" + self.request.sha256))
        self.saver = runs._graph.saver
        builder = StateGraph(MonthlyState)
        builder.add_node("execute_experiment", self._execute)
        builder.add_node("publish_manifest", self._publish)
        builder.add_edge(START, "execute_experiment")
        builder.add_edge("execute_experiment", "publish_manifest")
        builder.add_edge("publish_manifest", END)
        self.graph = builder.compile(checkpointer=self.saver)

    def _validate(self, state: object) -> MonthlyState:
        """Persisted values must match the trusted invocation before artifact or worker access."""
        if not isinstance(state, dict) or not all(
            isinstance(value, str) for value in state.values()
        ):
            raise ResearchError(
                "CHECKPOINT_CONFLICT", "The experiment checkpoint is inconsistent.", 409
            )
        if set(state) != set(self.initial) or any(
            state[key] != self.initial[key]
            for key in ("run_id", "owner_issuer", "owner_subject", "graph_version", "request_json")
        ):
            raise ResearchError(
                "CHECKPOINT_CONFLICT", "The experiment checkpoint is inconsistent.", 409
            )
        return cast(MonthlyState, state)

    def _execute(self, state: MonthlyState) -> dict[str, str]:
        """Budget replay recovers settled work if execution finished before its checkpoint saved."""
        self._validate(state)
        result = execute_monthly_operation(
            self.runs, self.run_id, self.principal, self.request, self.artifacts
        )
        return {"result_json": result.canonical_bytes().decode()}

    def _publish(self, state: MonthlyState) -> dict[str, str]:
        """Canonical budget evidence determines final publication."""
        self._validate(state)
        self.runs._inject("before_monthly_manifest")
        actual = (
            recover_monthly_operation(
                self.runs, self.run_id, self.principal, self.request, self.artifacts
            )
            .canonical_bytes()
            .decode()
        )
        if actual != state["result_json"]:
            raise ResearchError(
                "CHECKPOINT_CONFLICT", "The experiment result is inconsistent.", 409
            )
        raw = actual.encode()
        expected = ArtifactRef(
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            media_type="application/json",
        )
        if self.artifacts.put(raw, media_type="application/json") != expected:
            raise ResearchError(
                "RESEARCH_RESULT_INVALID", "The experiment manifest cannot be verified.", 409
            )
        return {"manifest_sha256": expected.sha256}

    @safe_checkpoint
    def finish(self) -> ArtifactRef:
        """Serialize graph writers and verify evidence before accepting a final checkpoint."""
        self.principal.require("execute_research")
        config: RunnableConfig = {"configurable": {"thread_id": self.thread}, "recursion_limit": 4}
        with self.runs._connection() as connection, connection.transaction():
            self.runs._owned(connection, self.run_id, self.principal)
            key = int.from_bytes(
                hashlib.sha256(self.thread.encode()).digest()[:8], "big", signed=True
            )
            locked = connection.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS locked", (key,)
            ).fetchone()
            if locked is None or not locked["locked"]:
                raise ResearchError(
                    "RESEARCH_BUSY", "The experiment already has an active worker.", 409
                )
            saved = self.saver.get_tuple(config)
            if saved is None:
                self.graph.invoke(self.initial, config, durability="sync")
            else:
                snapshot = self.graph.get_state(config)
                self._validate(snapshot.values)
                if snapshot.next:
                    self.graph.invoke(None, config, durability="sync")
            final = self.graph.get_state(config)
            verified = self._publish(self._validate(final.values))
            if final.next or final.values["manifest_sha256"] != verified["manifest_sha256"]:
                raise ResearchError(
                    "CHECKPOINT_CONFLICT", "The experiment checkpoint is incomplete.", 409
                )
            raw = final.values["result_json"].encode()
            return ArtifactRef(
                sha256=verified["manifest_sha256"],
                size_bytes=len(raw),
                media_type="application/json",
            )
