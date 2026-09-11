"""A genuine persisted graph performs only the trusted normalization stage in this slice."""

from collections.abc import Callable
from functools import wraps
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import InvalidModuleError
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from factorforge.domain.errors import ResearchError


def safe_checkpoint[**P, T](operation: Callable[P, T]) -> Callable[P, T]:
    """Malformed persisted values become typed failures without leaking serialization details."""

    @wraps(operation)
    def checked(*args: P.args, **kwargs: P.kwargs) -> T:
        """Handle checkpoint shape/codec errors while retaining connection failure semantics."""
        try:
            return operation(*args, **kwargs)
        except (
            ValueError,
            TypeError,
            KeyError,
            NotImplementedError,
            InvalidModuleError,
            GraphRecursionError,
        ):
            raise ResearchError(
                "CHECKPOINT_CORRUPT", "The saved run checkpoint cannot be verified.", 409
            ) from None

    return checked


class NormalizationState(TypedDict):
    """Plain checkpoint data binds execution to an immutable request and verified owner."""

    run_id: str
    owner_issuer: str
    owner_subject: str
    request_hash: str
    graph_version: str
    idea: str
    status: str
    brief: str


def normalize_brief(state: NormalizationState) -> dict[str, str]:
    """This pure node is safe to replay after a checkpoint failure and spends no model budget."""
    return {"status": "BRIEF_NORMALIZED", "brief": " ".join(state["idea"].split())}


class NormalizationGraph:
    """Checkpoint-first publication leaves canonical acceptance under application validation."""

    def __init__(self, saver: PostgresSaver) -> None:
        """Use the supported saver without duplicating its checkpoint format or migrations."""
        self.saver = saver
        builder = StateGraph(NormalizationState)
        builder.add_node("normalize_brief", normalize_brief)
        builder.add_edge(START, "normalize_brief")
        builder.add_edge("normalize_brief", END)
        self.graph = builder.compile(checkpointer=saver)

    @safe_checkpoint
    def checkpoint_id(self, run_id: str) -> str | None:
        """Return a real persisted identifier, never a synthetic application event ID."""
        checkpoint = self.saver.get_tuple(self.config(run_id))
        if checkpoint is None:
            return None
        return str(checkpoint.config["configurable"]["checkpoint_id"])

    def config(self, run_id: str) -> RunnableConfig:
        """Run UUIDs provide stable short thread identities without accepting caller namespaces."""
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 3}

    @safe_checkpoint
    def finish(self, expected: NormalizationState) -> tuple[str, str]:
        """Resume existing work or reuse a finished checkpoint before canonical publication."""
        config = self.config(expected["run_id"])
        saved = self.saver.get_tuple(config)
        if saved is None:
            self.graph.invoke(expected, config, durability="sync")
        else:
            snapshot = self.graph.get_state(config)
            self.validate_identity(snapshot.values, expected)
            if snapshot.next:
                self.graph.invoke(None, config, durability="sync")
        return self.verify_finished(expected)

    @safe_checkpoint
    def verify_finished(self, expected: NormalizationState) -> tuple[str, str]:
        """Read-only verification cannot create graph work when serving an accepted result."""
        config = self.config(expected["run_id"])
        snapshot = self.graph.get_state(config)
        self.validate_identity(snapshot.values, expected)
        if snapshot.next or snapshot.values.get("status") != "BRIEF_NORMALIZED":
            raise ResearchError("CHECKPOINT_CONFLICT", "The saved run state is inconsistent.", 409)
        brief = snapshot.values.get("brief")
        if not isinstance(brief, str) or brief != " ".join(expected["idea"].split()):
            raise ResearchError("CHECKPOINT_CONFLICT", "The saved brief is inconsistent.", 409)
        checkpoint_id = self.checkpoint_id(expected["run_id"])
        if checkpoint_id is None:
            raise ResearchError("CHECKPOINT_MISSING", "The run checkpoint is unavailable.", 503)
        return brief, checkpoint_id

    def validate_identity(self, actual: object, expected: NormalizationState) -> None:
        """Saved state cannot authorize publication with a different owner or request."""
        keys = ("run_id", "owner_issuer", "owner_subject", "request_hash", "graph_version", "idea")
        expected_values = dict(expected)
        if not isinstance(actual, dict) or any(
            actual.get(key) != expected_values[key] for key in keys
        ):
            raise ResearchError(
                "CHECKPOINT_CONFLICT", "The saved run identity is inconsistent.", 409
            )
