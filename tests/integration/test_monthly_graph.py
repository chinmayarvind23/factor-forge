"""Real LangGraph checkpoints resume from durable experiment results after process replacement."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_monthly_worker import request
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.errors import ResearchError
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.monthly_graph import MonthlyExperimentGraph
from factorforge.orchestration.postgres_runs import PostgresRunStore


def test_resume_after_execution_checkpoint(
    store: PostgresRunStore, database: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh graph instance resumes publication without running accounting twice."""
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original persisted experiment"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        command = request(artifacts)
        graph = MonthlyExperimentGraph(store, run.run_id, owner, command, artifacts)

        def crash(stage: str) -> None:
            """Stop publication after LangGraph has saved the completed execution node."""
            if stage == "before_monthly_manifest":
                raise RuntimeError("original publication crash")

        store.failpoint = crash
        with pytest.raises(RuntimeError, match="original publication crash"):
            graph.finish()
        assert graph.saver.get_tuple({"configurable": {"thread_id": graph.thread}}) is not None
        store.close()
        replacement = PostgresRunStore(database[0], schema=database[1], require_test_database=True)

        def no_repeat(*args: object, **kwargs: object) -> None:
            """Resume must read the canonical result rather than call the monthly executor."""
            raise AssertionError("duplicate execution")

        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        try:
            resumed = MonthlyExperimentGraph(replacement, run.run_id, owner, command, artifacts)
            result = resumed.finish()
            assert artifacts.get(result) and resumed.finish() == result
            snapshot = resumed.graph.get_state({"configurable": {"thread_id": resumed.thread}})
            assert not snapshot.next and snapshot.values["manifest_sha256"] == result.sha256
        finally:
            replacement.close()


@pytest.mark.parametrize("mutation", ["owner_subject", "result_json", "canonical_budget"])
def test_checkpoint_cannot_replace_canonical_authority(
    store: PostgresRunStore, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Changed checkpoint values or missing canonical settlement cannot authorize execution."""
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="Original persisted experiment"), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        graph = MonthlyExperimentGraph(store, run.run_id, owner, request(artifacts), artifacts)
        graph.finish()

        def no_repeat(*args: object, **kwargs: object) -> None:
            """Verification must never dispatch even if a canonical budget row is missing."""
            raise AssertionError("duplicate execution")

        monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        if mutation == "canonical_budget":
            with store._connection() as connection, connection.transaction():
                connection.execute("DELETE FROM research_budgets WHERE run_id=%s", (run.run_id,))
        else:
            graph.graph.update_state(
                {"configurable": {"thread_id": graph.thread}},
                {mutation: "original alteration"},
                as_node="publish_manifest",
            )
        with pytest.raises(ResearchError) as error:
            graph.finish()
        assert error.value.code in {"CHECKPOINT_CONFLICT", "RESEARCH_OPERATION_UNRESOLVED"}
