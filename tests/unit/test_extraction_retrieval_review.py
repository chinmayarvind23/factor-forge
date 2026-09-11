"""Independent extraction and retrieval probes use only fictional hand-ranked fixtures."""

import json
from typing import cast

import pytest
from pydantic import ValidationError

from factorforge.domain.errors import ResearchError
from factorforge.domain.extraction import SourceExtraction, parse_extraction
from factorforge.domain.literature import PaperDocument
from factorforge.evaluation.retrieval import (
    JudgedQuery,
    RetrievalCorpus,
    RetrievalJudgments,
    score_rankings,
)


def source() -> RetrievalCorpus:
    """Two original documents are sufficient to expose ordered ranking and strict labels."""
    return RetrievalCorpus(
        version="review-v1",
        status="frozen",
        documents=tuple(
            PaperDocument(
                paper_id=name,
                title=name,
                text=name,
                source_url="https://example.invalid",
                source_version="review-v1",
                content_kind="original_summary",
            )
            for name in ("a", "b")
        ),
    )


def labels(corpus: RetrievalCorpus) -> RetrievalJudgments:
    """One relevant document gives a hand-computable reciprocal rank without using pilot gold."""
    return RetrievalJudgments(
        version="review-v1",
        status="frozen",
        corpus_sha256=corpus.sha256,
        queries=(JudgedQuery(query_id="q", text="a", judgments={"a": 1, "b": 0}),),
    )


@pytest.mark.parametrize("ranking", [{"a", "b"}, {"a": 1, "b": 0}, None, 2, iter(["a"])])
def test_unordered_or_invalid_rankings_fail_with_safe_error(ranking: object) -> None:
    """An unordered container cannot be silently converted to a meaningful retrieval rank."""
    corpus = source()
    with pytest.raises(ResearchError) as failure:
        score_rankings(corpus, labels(corpus), cast(dict[str, list[str]], {"q": ranking}))
    assert failure.value.code == "RETRIEVAL_EVAL_INVALID"


@pytest.mark.parametrize("rankings", [None, 3, ["q"], {"q"}])
def test_invalid_query_mapping_fails_with_safe_error(rankings: object) -> None:
    """The external rank inventory must be a mapping, not an accidental iterable or scalar."""
    corpus = source()
    with pytest.raises(ResearchError) as failure:
        score_rankings(corpus, labels(corpus), cast(dict[str, list[str]], rankings))
    assert failure.value.code == "RETRIEVAL_EVAL_INVALID"


def extracted() -> dict[str, object]:
    """Unknown strategy fields remain explicit nulls in a fictional source observation."""
    return {
        "status": "extracted",
        "refusal_reason": None,
        "refusal_category": None,
        "formula": None,
        "required_inputs": [],
        "long_short_direction": None,
        "bucket_count": None,
        "weighting": None,
        "lookback_months": None,
        "holding_months": None,
        "rebalance_frequency": None,
        "formation_lag_months": None,
        "formation_rule": None,
        "source_pages": [1],
    }


@pytest.mark.parametrize("field", ["formula", "formation_rule", "refusal_reason"])
def test_escaped_lone_surrogate_is_not_portable_extraction_text(field: str) -> None:
    """JSON escapes must not admit strings that cannot later be encoded as UTF-8 evidence."""
    value = extracted()
    if field == "refusal_reason":
        value.update(status="refused", refusal_category="input_mismatch", source_pages=[])
    value[field] = "invalid \ud800 text"
    with pytest.raises(ResearchError) as failure:
        parse_extraction(json.dumps(value))
    assert failure.value.code == "EXTRACTION_INVALID"


def test_mutated_nested_labels_are_revalidated_before_scoring() -> None:
    """Frozen outer models cannot hide mutation of a nested dictionary across admission."""
    corpus = source()
    qrels = labels(corpus)
    qrels.queries[0].judgments["a"] = 2
    with pytest.raises(ResearchError):
        score_rankings(corpus, qrels, {"q": ["a"]})


def test_forged_extraction_and_changed_lists_are_revalidated() -> None:
    """A model instance is not a trusted substitute for the extraction field contract."""
    result = SourceExtraction.model_validate(extracted())
    result.source_pages.append(1)
    with pytest.raises(ValidationError):
        SourceExtraction.model_validate(result)
    forged = result.model_copy(update={"holding_months": True})
    with pytest.raises(ValidationError):
        SourceExtraction.model_validate(forged)


def test_valid_unicode_and_escaped_brackets_survive_without_repair() -> None:
    """Real non-ASCII text and escaped punctuation retain their exact field content."""
    text = 'café 😀 "\\' + "[" * 100
    result = parse_extraction(json.dumps(extracted() | {"formula": text}))
    assert result.formula == text


@pytest.mark.parametrize("missing", ["refusal_reason", "refusal_category"])
def test_refusal_requires_both_nonnull_explanatory_fields(missing: str) -> None:
    """A refusal must remain attributable even when every strategy quantity is unknown."""
    value = extracted() | {
        "status": "refused",
        "refusal_reason": "Unrelated passage.",
        "refusal_category": "input_mismatch",
        "source_pages": [],
        missing: None,
    }
    with pytest.raises(ResearchError):
        parse_extraction(json.dumps(value))


def test_finite_fraction_does_not_coerce_an_integer_strategy_field() -> None:
    """Valid JSON numeric syntax still must satisfy the strict integer extraction contract."""
    with pytest.raises(ResearchError):
        parse_extraction(json.dumps(extracted() | {"bucket_count": 3.0}))


def test_multibyte_utf8_admission_uses_bytes_not_character_count() -> None:
    """A compact character count cannot bypass the declared 32-KiB UTF-8 input limit."""
    value = extracted() | {"formula": "😀" * 2000, "formation_rule": "😀" * 2000}
    raw = " " * 20000 + json.dumps(value, ensure_ascii=False)
    assert len(raw) < 32768 < len(raw.encode("utf-8"))
    with pytest.raises(ResearchError):
        parse_extraction(raw)


def test_per_query_rank_and_denominator_match_hand_calculation() -> None:
    """The relevant second document contributes reciprocal rank one half and recall one."""
    corpus = source()
    report = score_rankings(corpus, labels(corpus), {"q": ("b", "a")}, k=2)
    assert report.mrr_at_k == 0.5 and report.recall_at_k == 1
    assert report.query_results[0].relevant_count == 1
    assert report.query_results[0].relevant_returned == 1
    assert report.query_results[0].returned_ids == ("b", "a")
