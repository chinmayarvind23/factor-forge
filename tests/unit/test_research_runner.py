"""Controlled workers verify batch dispatch boundaries without spending model budgets."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_budgets import ledger
from test_monthly_admission import MemoryStore

from factorforge.data.synthesis_fixture import prepare_synthesis_fixture
from factorforge.domain.errors import ResearchError
from factorforge.evaluation.research_batch import ResearchCase, ResearchSuite, evaluate_batch
from factorforge.evaluation.research_runner import Request, run_research_batch
from factorforge.factors.hybrid import publish
from factorforge.orchestration.postgres_runs import request_hash
from factorforge.orchestration.synthesis_command import SynthesisResearchResult


def suite_fixture() -> tuple[ResearchSuite, MemoryStore]:
    """Distinct authored ideas share reviewed sources without aliasing identical requests."""
    store = MemoryStore()
    first = prepare_synthesis_fixture(Path(__file__).resolve().parents[2], store)
    second = first.model_copy(
        update={"brief": first.brief.model_copy(update={"idea": "A second authored research case"})}
    )
    return ResearchSuite(
        cases=(
            ResearchCase(case_id="first", request=publish(first, store)),
            ResearchCase(case_id="second", request=publish(second, store)),
        )
    ), store


def held(request: Request, store: MemoryStore) -> SynthesisResearchResult:
    """A valid held receipt tests evidence settlement separately from rubric success."""
    budget = ledger(request_sha256=request_hash(request.brief))
    return SynthesisResearchResult(
        run_id=budget.run_id,
        request=publish(request, store),
        strategies=None,
        reviews=(),
        synthesis=None,
        hybrid=None,
        status="held",
        reasons=("INSUFFICIENT_REVIEWED_PARENTS",),
        budget=publish(budget, store),
    )


@pytest.mark.parametrize("outcome", ["held", "exception", "wrong_request"])
def test_dispatch_is_durable_and_failures_remain_in_denominator(outcome: str) -> None:
    """Every call sees its persisted key; one case's failure never drops the second case."""
    suite, store = suite_fixture()
    keys = []
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "journal.jsonl"

        def execute(request: Request, key: str) -> SynthesisResearchResult:
            """Observe the real flushed journal before returning controlled worker evidence."""
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            assert rows[-1]["event"] == "case_dispatch"
            assert rows[-1]["idempotency_key"] == key
            keys.append(key)
            if len(keys) == 1 and outcome == "exception":
                raise RuntimeError("private provider payload must not be recorded")
            result = held(request, store)
            if len(keys) == 1 and outcome == "wrong_request":
                return result.model_copy(update={"request": suite.cases[1].request})
            return result

        result = run_research_batch(
            suite, store, execute, journal_path=path, max_reserved_microusd=200000000
        )
        score = evaluate_batch(suite, result, store)
        assert score["total"] == 2 and score["criteria_passes"] == 0
        assert len(result.results) == (1 if outcome == "exception" else 2)
        assert score["missing"] == (1 if outcome == "exception" else 0)
        assert score["invalid"] == (1 if outcome == "wrong_request" else 0)
        assert len(set(keys)) == 2
        assert "private provider payload" not in path.read_text()
        with pytest.raises(FileExistsError):
            run_research_batch(
                suite, store, execute, journal_path=path, max_reserved_microusd=200000000
            )
        assert len(keys) == 2


@pytest.mark.parametrize("failure", ["budget", "corruption"])
def test_complete_preflight_precedes_any_dispatch(failure: str) -> None:
    """A bad later case or excess aggregate reservation prevents the entire batch starting."""
    suite, store = suite_fixture()
    if failure == "corruption":
        store.values[suite.cases[1].request.sha256] = b"tampered"
    calls = []

    def execute(request: Request, key: str) -> SynthesisResearchResult:
        """The test must never enter its worker when any case fails preflight."""
        calls.append(key)
        return held(request, store)

    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "journal.jsonl"
        with pytest.raises((ValueError, ResearchError)):
            run_research_batch(
                suite,
                store,
                execute,
                journal_path=path,
                max_reserved_microusd=1 if failure == "budget" else 200000000,
            )
        assert not calls and not path.exists()


@pytest.mark.parametrize("failed_sync,expected_calls", [(1, 0), (3, 1)])
def test_journal_failure_stops_dispatch(
    monkeypatch: pytest.MonkeyPatch, failed_sync: int, expected_calls: int
) -> None:
    """A durability error before or after a worker stops the remaining batch immediately."""
    suite, store = suite_fixture()
    syncs = 0
    calls = 0

    def sync(handle: int) -> None:
        """Inject a disk boundary error without depending on filesystem permissions."""
        nonlocal syncs
        syncs += 1
        if syncs == failed_sync:
            raise OSError("controlled disk failure")

    def execute(request: Request, key: str) -> SynthesisResearchResult:
        """Count irreversible dispatches before the injected journal failure."""
        nonlocal calls
        calls += 1
        return held(request, store)

    monkeypatch.setattr("factorforge.evaluation.research_runner.os.fsync", sync)
    with TemporaryDirectory() as temporary, pytest.raises(OSError):
        run_research_batch(
            suite,
            store,
            execute,
            journal_path=Path(temporary) / "journal",
            max_reserved_microusd=200000000,
        )
    assert calls == expected_calls
