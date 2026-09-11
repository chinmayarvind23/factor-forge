"""Hand-ranked original documents define retrieval denominators before any pilot evaluation."""

import math

import pytest
from pydantic import ValidationError

from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import PaperDocument
from factorforge.evaluation.retrieval import (
    JudgedQuery,
    RetrievalCorpus,
    RetrievalJudgments,
    evaluate_retrieval,
    score_rankings,
)


def corpus() -> RetrievalCorpus:
    """Create original test text, unrelated to the prepared research pilot."""
    return RetrievalCorpus(
        version="test-v1",
        status="frozen",
        documents=tuple(
            PaperDocument(
                paper_id=name,
                title="!",
                text=text,
                source_url="https://example.invalid",
                source_version="test-v1",
                content_kind="original_summary",
            )
            for name, text in [("a", "apple"), ("b", "pear"), ("c", "orange")]
        ),
    )


def judgments(source: RetrievalCorpus) -> RetrievalJudgments:
    """Two answerable and two unanswerable queries expose denominators independently."""
    return RetrievalJudgments(
        version="test-qrels-v1",
        status="frozen",
        corpus_sha256=source.sha256,
        queries=(
            JudgedQuery(query_id="q1", text="apple pear", judgments={"a": 1, "b": 1, "c": 0}),
            JudgedQuery(query_id="q2", text="orange", judgments={"a": 0, "b": 0, "c": 1}),
            JudgedQuery(query_id="q3", text="unknown", judgments={"a": 0, "b": 0, "c": 0}),
            JudgedQuery(query_id="q4", text="unrelated", judgments={"a": 0, "b": 0, "c": 0}),
        ),
    )


def test_hand_rankings_have_explicit_answerable_and_no_relevant_denominators() -> None:
    """At k=2, recalls are 1/2 and 1; reciprocal ranks are 1/2 and 1, despite two negatives."""
    source = corpus()
    result = score_rankings(
        source,
        judgments(source),
        {"q1": ["c", "a", "b"], "q2": ["c"], "q3": ["a", "b"], "q4": []},
        k=2,
    )
    assert result.answerable_queries == 2 and result.no_relevant_queries == 2
    assert result.recall_at_k == 0.75 and result.mrr_at_k == 0.75
    assert result.no_relevant_false_positive_rate == 0.5
    assert result.no_relevant_abstention_rate == 0.5
    assert result.no_relevant_returned_documents == 2
    assert result.query_results[0].returned_ids == ("c", "a")
    assert result.query_results[2].recall_at_k is None
    assert result.query_results[2].reciprocal_rank_at_k is None


def test_relevant_beyond_k_is_a_miss_not_full_reciprocal_rank() -> None:
    """A relevant second result cannot improve metrics at cutoff one."""
    source = corpus()
    result = score_rankings(
        source, judgments(source), {"q1": ["c", "a"], "q2": [], "q3": [], "q4": []}, k=1
    )
    assert result.recall_at_k == 0 and result.mrr_at_k == 0


@pytest.mark.parametrize("answerable", [True, False])
def test_empty_metric_partition_is_null_not_perfect(answerable: bool) -> None:
    """No applicable queries means undefined macro metrics, never zero or perfect recall."""
    source = corpus()
    selected = judgments(source).queries[:2] if answerable else judgments(source).queries[2:]
    qrels = RetrievalJudgments(
        version="partition-v1", status="frozen", corpus_sha256=source.sha256, queries=selected
    )
    result = score_rankings(source, qrels, {query.query_id: [] for query in selected}, k=3)
    if answerable:
        assert result.no_relevant_false_positive_rate is None
        assert result.no_relevant_abstention_rate is None
    else:
        assert result.recall_at_k is None and result.mrr_at_k is None


def test_identity_changes_with_query_text_version_or_document_content() -> None:
    """Canonical metadata binds source contents, qrel versions and the exact query wording."""
    source = corpus()
    qrels = judgments(source)
    changed = source.model_copy(update={"version": "test-v2"})
    assert changed.sha256 != source.sha256
    query = qrels.queries[0].model_copy(update={"text": "different"})
    changed_qrels = qrels.model_copy(update={"queries": (query, *qrels.queries[1:])})
    assert changed_qrels.sha256 != qrels.sha256
    assert query.sha256 != qrels.queries[0].sha256
    changed_document = source.documents[0].model_copy(update={"text": "different"})
    assert (
        source.model_copy(update={"documents": (changed_document, *source.documents[1:])}).sha256
        != source.sha256
    )
    with pytest.raises(ResearchError, match="corpus identity"):
        score_rankings(changed, qrels, {query.query_id: [] for query in qrels.queries})


@pytest.mark.parametrize("value", [True, False, -1, 2, 1.0, math.nan, "1"])
def test_binary_labels_are_strict_integers(value: object) -> None:
    """Booleans, grades and coerced values cannot silently redefine binary relevance."""
    with pytest.raises(ValidationError):
        JudgedQuery.model_validate({"query_id": "q", "text": "query", "judgments": {"a": value}})


def test_duplicates_and_unfrozen_contracts_fail() -> None:
    """Input identity cannot be overwritten by repeated IDs or a draft label."""
    source = corpus()
    with pytest.raises(ValidationError):
        RetrievalCorpus(version="v1", status="frozen", documents=(source.documents[0],) * 2)
    qrels = judgments(source)
    with pytest.raises(ValidationError):
        RetrievalJudgments(
            version="v1",
            status="frozen",
            corpus_sha256=source.sha256,
            queries=(qrels.queries[0],) * 2,
        )
    with pytest.raises(ValidationError):
        RetrievalCorpus.model_validate({**source.model_dump(), "status": "draft"})


@pytest.mark.parametrize(
    "change",
    [
        "missing_judgment",
        "extra_judgment",
        "missing_query",
        "extra_query",
        "duplicate_rank",
        "foreign_rank",
    ],
)
def test_incomplete_or_unjudged_rankings_fail(change: str) -> None:
    """The closed corpus requires every pair and ranking ID to be explicitly accounted for."""
    source = corpus()
    qrels = judgments(source)
    ranks: dict[str, list[str]] = {query.query_id: [] for query in qrels.queries}
    if change in {"missing_judgment", "extra_judgment"}:
        values = dict(qrels.queries[0].judgments)
        if change == "missing_judgment":
            values.pop("c")
        else:
            values["outside"] = 0
        query = qrels.queries[0].model_copy(update={"judgments": values})
        qrels = qrels.model_copy(update={"queries": (query, *qrels.queries[1:])})
    elif change == "missing_query":
        ranks.pop("q1")
    elif change == "extra_query":
        ranks["outside"] = []
    elif change == "duplicate_rank":
        ranks["q1"] = ["a", "a"]
    else:
        ranks["q1"] = ["a", "outside"]
    with pytest.raises(ResearchError):
        score_rankings(source, qrels, ranks, k=1)


def test_runner_uses_positive_results_without_a_tuned_threshold() -> None:
    """Only original test queries run here; no prepared pilot judgments are evaluated."""
    source = corpus()
    report = evaluate_retrieval(source, judgments(source), k=3)
    assert report.recall_at_k == 1 and report.mrr_at_k == 1
    assert report.no_relevant_abstention_rate == 1
    assert report.corpus_sha256 == source.sha256
    assert report.qrels_sha256 == judgments(source).sha256
    assert all(row.query_sha256 for row in report.query_results)


@pytest.mark.parametrize("cutoff", [True, 0, 21, 1.0])
def test_invalid_cutoff_does_not_change_metric_definition(cutoff: object) -> None:
    """Coercing cutoffs would make an evaluation claim differ from its declared configuration."""
    source = corpus()
    with pytest.raises(ResearchError):
        score_rankings(source, judgments(source), {}, k=cutoff)  # type: ignore[arg-type]


@pytest.mark.parametrize("ranking", ["a", ["a", "b", "c", "a"]])
def test_string_or_oversized_ranking_is_not_a_valid_inventory(ranking: object) -> None:
    """Validate the full supplied list before cutoff so hidden duplicate tails cannot pass."""
    source = corpus()
    ranks: dict[str, list[str]] = {query.query_id: [] for query in judgments(source).queries}
    with pytest.raises(ResearchError):
        score_rankings(source, judgments(source), ranks | {"q1": ranking})  # type: ignore[arg-type]


def test_blank_queries_and_oversized_corpora_are_rejected() -> None:
    """Corpus byte admission prevents a valid document count from bypassing memory limits."""
    with pytest.raises(ValidationError):
        JudgedQuery(query_id="blank", text=" \t", judgments={"a": 0})
    base = corpus().documents[0]
    documents = tuple(
        base.model_copy(
            update={
                "paper_id": f"paper-{index}",
                "text": "x" * 16000,
                "title": "x" * 500,
                "source_version": "x" * 200,
            }
        )
        for index in range(500)
    )
    with pytest.raises(ValidationError, match="byte limit"):
        RetrievalCorpus(version="oversized", status="frozen", documents=documents)
