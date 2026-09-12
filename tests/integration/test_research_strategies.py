"""Actual PostgreSQL source workers feed retained, executable strategy drafts."""

import json
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from test_monthly_worker import request as monthly_request
from test_postgres_runs import database as database
from test_postgres_runs import store as store

from factorforge.auth.principal import Principal
from factorforge.backtests.monthly import MonthlyRun, run_monthly
from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import PaperDocument
from factorforge.domain.research_brief import ResearchBrief
from factorforge.orchestration.command import OPERATOR, OperatorRequest
from factorforge.orchestration.command import main as operator_main
from factorforge.orchestration.postgres_budgets import read_budget
from factorforge.orchestration.postgres_runs import PostgresRunStore
from factorforge.orchestration.report_export import ResearchCompletion
from factorforge.orchestration.research_experiments import (
    ExperimentPlan,
    ResearchExperiments,
    research_experiments,
)
from factorforge.orchestration.research_report import build_report, render_report
from factorforge.orchestration.research_strategies import (
    ReviewedStrategyBinding,
    _publish,
    research_strategies,
)
from factorforge.providers.ollama import GenerationRequest, GenerationResult
from factorforge.retrieval.extraction import SourcePacket, SourcePage
from factorforge.retrieval.selection import LiteratureCatalog, LiteratureEntry
from factorforge.validation.monthly import MonthlyHACResult


@pytest.mark.parametrize("outcome", ["compiled", "unbound", "needs_review", "source_unavailable"])
@pytest.mark.parametrize(
    "workflow_pause",
    ["after_workflow_research_receipt", "before_workflow_report", "before_workflow_memory"],
)
def test_source_drafts_publish_and_replay(
    store: PostgresRunStore,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    workflow_pause: str,
    database: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A controlled extraction becomes a draft with retained source evidence and one model call."""
    calls = []

    class Provider:
        """Original observations exercise orchestration without a source-accuracy claim."""

        def __init__(self, *, deadline: float) -> None:
            """Require the durable worker's run deadline."""
            assert deadline > 0

        def generate(
            self, request: GenerationRequest, artifacts: ArtifactStore
        ) -> GenerationResult:
            """Retain the controlled response as provider evidence."""
            calls.append(request)
            return GenerationResult(
                status="unavailable" if outcome == "source_unavailable" else "success",
                record=artifacts.put(b"{}", media_type="application/json"),
                content=json.dumps(
                    {
                        "status": "extracted",
                        "refusal_reason": None,
                        "refusal_category": None,
                        "formula": "score",
                        "required_inputs": ["score"],
                        "long_short_direction": "long_high_short_low",
                        "bucket_count": 2,
                        "weighting": "equal_weight",
                        "lookback_months": None,
                        "holding_months": 12 if outcome == "needs_review" else 1,
                        "rebalance_frequency": "monthly",
                        "formation_lag_months": 0,
                        "formation_rule": "Last session close each month",
                        "source_pages": [1],
                    }
                ),
            )

    monkeypatch.setattr("factorforge.orchestration.extraction_worker.OllamaProvider", Provider)
    owner = Principal("fixture", "owner", frozenset({"execute_research"}))
    run = store.create(ResearchBrief(idea="original score", max_experiments=1), "one", owner)
    with TemporaryDirectory() as directory:
        artifacts = LocalArtifactStore(Path(directory))
        command = monthly_request(artifacts)
        source = SourcePacket(
            paper_id="original",
            source_sha256="a" * 64,
            selected_strategy="original score",
            pages=(
                SourcePage(
                    pdf_page=1,
                    artifact=artifacts.put(b"Original score strategy", media_type="text/plain"),
                ),
            ),
        )
        catalog = LiteratureCatalog(
            entries=(
                LiteratureEntry(
                    source=source,
                    document=PaperDocument(
                        paper_id="original",
                        title="original score",
                        text="original score",
                        source_url="https://example.org/original",
                        source_sha256="a" * 64,
                        content_kind="original_summary",
                        source_version="v1",
                    ),
                ),
            )
        )
        bindings = (
            (
                ReviewedStrategyBinding(
                    source=source,
                    environment=command.spec,
                    reviewed_formation_rule="Last session close each month",
                ),
            )
            if outcome != "unbound"
            else ()
        )
        result = research_strategies(
            store,
            run.run_id,
            owner,
            catalog,
            bindings,
            artifacts,
            max_cost_per_source_microusd=1000000,
        )
        candidate = result.candidates[0]
        assert candidate.status == outcome
        if outcome in {"compiled", "needs_review"}:
            assert candidate.draft is not None and candidate.artifact is not None
            assert artifacts.get(candidate.artifact) == candidate.draft.canonical_bytes()
        if outcome == "compiled":
            assert candidate.draft is not None and candidate.draft.strategy is not None
            assert result.sources.extractions[0].record in candidate.draft.strategy.source_refs
        plan = ExperimentPlan(
            catalog=catalog,
            bindings=bindings,
            initial_cash_usd=command.initial_cash_usd,
            evaluated_at=command.evaluated_at,
            max_cost_per_source_microusd=1000000,
            hac_lags=1,
        )
        if outcome == "compiled":

            def interrupt_publication(stage: str) -> None:
                """Interrupt after durable execution so the scheduler must resume the graph."""
                if stage == "before_monthly_manifest":
                    raise RuntimeError("original publication interruption")

            store.failpoint = interrupt_publication
            with pytest.raises(RuntimeError, match="original publication interruption"):
                research_experiments(store, run.run_id, owner, plan, artifacts)
            store.failpoint = None

            def no_repeat(*args: object, **kwargs: object) -> None:
                """Replaying scheduling must use settled evidence rather than rerun accounting."""
                raise AssertionError("duplicate monthly execution")

            monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
        scheduled = research_experiments(store, run.run_id, owner, plan, artifacts)
        assert isinstance(scheduled, ResearchExperiments)
        report = build_report(_publish(scheduled, artifacts), artifacts)
        assert len(report.candidates) == 1 and report.factor_promotion == "not_assessed"
        assert report.candidates[0].result == scheduled.experiments[0].result
        assert "[Scheduler result](sha256/" in render_report(report)
        if outcome == "compiled":
            assert report.candidates[0].terminal_nav_usd == Decimal("1057.98")
            altered = scheduled.model_copy(
                update={
                    "experiments": (
                        scheduled.experiments[0].model_copy(update={"status": "skipped"}),
                    )
                }
            )
            with pytest.raises(ResearchError) as report_error:
                build_report(_publish(altered, artifacts), artifacts)
            assert report_error.value.code == "REPORT_EVIDENCE_INVALID"
        else:
            assert report.candidates[0].terminal_nav_usd is None
        assert scheduled.experiments[0].status == (
            "completed" if outcome == "compiled" else "skipped"
        )
        if outcome == "compiled":
            reference = scheduled.experiments[0].result
            assert reference is not None
            executed = MonthlyRun.model_validate_json(artifacts.get(reference))
            assert executed.performance is not None
            assert executed.performance.terminal_nav_usd == Decimal("1057.98")
            validation_ref = scheduled.experiments[0].validation
            assert validation_ref is not None
            validation = MonthlyHACResult.model_validate_json(artifacts.get(validation_ref))
            assert validation.request.result == reference and validation.diagnostic is not None
            assert validation.diagnostic.request.lags == 1
        assert research_experiments(store, run.run_id, owner, plan, artifacts) == scheduled
        if outcome == "compiled":
            changed_plan = plan.model_copy(update={"initial_cash_usd": Decimal("1004")})
            stopped = research_experiments(store, run.run_id, owner, changed_plan, artifacts)
            assert isinstance(stopped, ResearchExperiments)
            assert stopped.experiments[0].status == "budget_stopped"
            assert stopped.experiments[0].reason == "RESEARCH_BUDGET_REJECTED"
            assert stopped.experiments[0].result is None
            assert research_experiments(store, run.run_id, owner, plan, artifacts) == scheduled
        assert (
            research_strategies(
                store,
                run.run_id,
                owner,
                catalog,
                bindings,
                artifacts,
                max_cost_per_source_microusd=1000000,
            )
            == result
        )
        assert len(calls) == 1
        assert len(read_budget(store, run.run_id, owner).operations) == (
            2 if outcome == "compiled" else 1
        )
        if bindings:
            changed = bindings[0].model_copy(
                update={
                    "source": source.model_copy(update={"selected_strategy": "another strategy"})
                }
            )
            with pytest.raises(ResearchError) as error:
                research_strategies(
                    store,
                    run.run_id,
                    owner,
                    catalog,
                    (changed,),
                    artifacts,
                    max_cost_per_source_microusd=1000000,
                )
            assert error.value.code == "STRATEGY_BINDING_INVALID" and len(calls) == 1
        if outcome == "compiled":
            monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", run_monthly)
            monkeypatch.setenv("RDS_DSN", database[0])
            operator_request = OperatorRequest(
                brief=ResearchBrief(idea="original score", max_experiments=1), plan=plan
            )
            request_path = Path(directory) / "operator-request.json"
            request_path.write_bytes(operator_request.canonical_bytes())
            args = [
                "--request",
                str(request_path),
                "--artifacts",
                directory,
                "--schema",
                database[1],
            ]
            assert operator_main(args) == 0
            first = capsys.readouterr()
            assert first.err == "" and len(first.out.splitlines()) == 2
            assert len(calls) == 2
            monkeypatch.setattr("factorforge.orchestration.monthly_worker.run_monthly", no_repeat)
            assert operator_main(args) == 0
            second = capsys.readouterr()
            assert first.out == second.out and second.err == "" and len(calls) == 2

            operator_run_id = UUID(json.loads(first.out.splitlines()[0])["run_id"])
            before_report = read_budget(store, operator_run_id, OPERATOR)
            assert operator_main([*args, "--report"]) == 0
            with_report = capsys.readouterr()
            lines = with_report.out.splitlines()
            assert with_report.err == "" and len(lines) == 3
            assert lines[:2] == first.out.splitlines()
            receipt = json.loads(lines[2])
            completion = ResearchCompletion.model_validate_json(
                artifacts.get(ArtifactRef.model_validate(receipt["completion"]))
            )
            assert completion.run_id == operator_run_id
            assert artifacts.get(completion.budget) == before_report.canonical_bytes()
            assert completion.result.model_dump(mode="json") == json.loads(lines[1])["result"]
            assert completion.request.model_dump(mode="json") == json.loads(lines[0])["request"]
            report_path = Path(receipt["path"])
            report_bytes = report_path.read_bytes()
            assert b"Terminal account NAV: 1057.98 USD." in report_bytes
            report_path.write_bytes(b"user edited report")
            assert operator_main([*args, "--report"]) == 1
            rejected = capsys.readouterr()
            assert "REPORT_EXPORT_INVALID" in rejected.err
            assert report_path.read_bytes() == b"user edited report"
            report_path.write_bytes(report_bytes)
            assert operator_main([*args, "--report"]) == 0
            resumed = capsys.readouterr()
            assert resumed.out == with_report.out and resumed.err == ""
            assert len(calls) == 2
            assert read_budget(store, operator_run_id, OPERATOR) == before_report

            assert operator_main([*args, "--workflow"]) == 0
            workflow_output = capsys.readouterr()
            assert workflow_output.out == with_report.out and workflow_output.err == ""
            assert operator_main([*args, "--memory-query", "score"]) == 0
            memory_output = json.loads(capsys.readouterr().out)
            assert len(memory_output) == 1
            assert memory_output[0]["completion"] == receipt["completion"]

        from factorforge.orchestration.research_workflow import ResearchWorkflow, search_memory

        workflow_request = OperatorRequest(
            brief=ResearchBrief(idea="original score", max_experiments=1), plan=plan
        )
        workflow = ResearchWorkflow(store, run.run_id, owner, workflow_request, artifacts)
        before_workflow = read_budget(store, run.run_id, owner)
        before_calls = len(calls)

        def stop_after_research(stage: str) -> None:
            """Crash after canonical research publication but before the report checkpoint."""
            if stage == workflow_pause:
                raise RuntimeError("workflow report interruption")

        store.failpoint = stop_after_research
        with pytest.raises(RuntimeError, match="workflow report interruption"):
            workflow.finish()
        store.failpoint = None

        def no_research_repeat(*args: object, **kwargs: object) -> None:
            """Resume must recover the whole research result without entering the scheduler."""
            raise AssertionError("duplicate research scheduling")

        monkeypatch.setattr(
            "factorforge.orchestration.research_workflow.research_experiments", no_research_repeat
        )
        with closing(
            PostgresRunStore(database[0], schema=database[1], require_test_database=True)
        ) as fresh:
            resumed_workflow = ResearchWorkflow(
                fresh, run.run_id, owner, workflow_request, artifacts
            )
            completed = resumed_workflow.finish()
            assert resumed_workflow.finish() == completed
            assert read_budget(fresh, run.run_id, owner) == before_workflow
            assert len(calls) == before_calls
            memory = search_memory(fresh, owner, "score")
            assert len(memory) == 1 and memory[0].completion == completed
            assert search_memory(fresh, owner, "unrelated") == ()
            stranger = Principal("fixture", "stranger", owner.capabilities)
            assert search_memory(fresh, stranger, "score") == ()
            with pytest.raises(ResearchError, match="No run exists"):
                ResearchWorkflow(fresh, run.run_id, stranger, workflow_request, artifacts).finish()
            resumed_workflow.graph.update_state(
                {"configurable": {"thread_id": resumed_workflow.thread}},
                {"result": "{}"},
                as_node="remember",
            )
            with pytest.raises(ResearchError):
                resumed_workflow.finish()
