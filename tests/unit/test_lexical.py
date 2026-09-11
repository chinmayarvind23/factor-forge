"""Independent arithmetic and adversarial inputs define the fixed retrieval baseline."""

import hashlib
import math

import pytest
from pydantic import ValidationError

from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import LexicalHit, PaperDocument
from factorforge.retrieval.lexical import BM25Index


def paper(identifier: str, text: str, title: str = "!") -> PaperDocument:
    """Construct original test text without depending on a corpus or relevance judgments."""
    return PaperDocument(
        paper_id=identifier,
        title=title,
        text=text,
        source_url="https://example.org/paper",
        source_version="original-v1",
        content_kind="original_summary",
    )


def test_two_document_scores_match_hand_calculated_bm25() -> None:
    """N=2, df=1, lengths3/1 and average2 give an independently calculated first-term score."""
    index = BM25Index([paper("one", "apple apple pear"), paper("two", "pear")])
    hits = index.search("apple")
    assert len(hits) == 1 and hits[0].document.paper_id == "one"
    # Positive IDF=log2; denominator=2+1.2*(.25+.75*1.5)=3.65.
    assert hits[0].score == pytest.approx(math.log(2) * 4.4 / 3.65, rel=1e-14)
    pear = index.search("pear")
    assert [hit.document.paper_id for hit in pear] == ["two", "one"]
    assert pear[0].score == pytest.approx(math.log(1.2) * 2.2 / 1.75, rel=1e-14)


def test_frequency_saturates_and_length_normalization_affects_ranking() -> None:
    """Repeated matches help at equal length; irrelevant padding lowers a one-match score."""
    index = BM25Index([paper("once", "value other other"), paper("twice", "value value other")])
    hits = index.search("value")
    assert [hit.document.paper_id for hit in hits] == ["twice", "once"]
    assert 1 < hits[0].score / hits[1].score < 2
    padded = BM25Index([paper("long", "value extra padding"), paper("short", "value")])
    assert [hit.document.paper_id for hit in padded.search("value")] == ["short", "long"]


def test_ties_query_order_and_document_order_are_deterministic() -> None:
    """Input order, query repetitions and token order cannot change tied document identity order."""
    documents = [paper("z", "gross value"), paper("a", "gross value")]
    first = BM25Index(documents).search("GROSS value gross")
    second = BM25Index(reversed(documents)).search("value gross")
    assert first == second
    assert [hit.document.paper_id for hit in first] == ["a", "z"]
    assert BM25Index(documents).search("gross", limit=1)[0].document.paper_id == "a"


def test_unicode_title_and_punctuation_tokenization_is_explicit() -> None:
    """Unicode casefold/alphanumeric tokens include titles but do not stem or remove accents."""
    index = BM25Index([paper("one", "Café STRASSE alpha_beta", title="MOMENTUM")])
    for query in ("café", "straße", "alpha beta", "momentum"):
        assert len(index.search(query)) == 1
    for query in ("cafe", "momentums", "unknown", "!!!", "", " \n"):
        assert index.search(query) == ()
    assert BM25Index([]).search("anything") == ()
    assert BM25Index([paper("empty", "", title="...")]).search("anything") == ()


def test_document_identity_is_frozen_and_separate_from_upstream_hash() -> None:
    """Canonical document bytes bind indexing metadata without pretending summaries are sources."""
    document = paper("one", "exact text")
    assert document.content_sha256 == hashlib.sha256(document.canonical_bytes()).hexdigest()
    changed = PaperDocument.model_validate({**document.model_dump(), "text": "changed text"})
    assert changed.content_sha256 != document.content_sha256
    upstream = PaperDocument.model_validate({**document.model_dump(), "source_sha256": "a" * 64})
    assert upstream.source_sha256 == "a" * 64
    assert upstream.content_sha256 != upstream.source_sha256
    with pytest.raises(ValidationError):
        document.text = "mutation"


@pytest.mark.parametrize(
    "updates",
    [
        {"paper_id": "../escape"},
        {"paper_id": "x" * 129},
        {"title": ""},
        {"title": " "},
        {"title": "x" * 501},
        {"text": "x" * 16001},
        {"text": "\ud800"},
        {"text": "\x00hidden"},
        {"source_url": "http://example.org"},
        {"source_url": "https://user:secret@example.org"},
        {"source_url": "https://example.org/#"},
        {"source_url": "https://example.org#part"},
        {"source_url": "https://example.org/\npart"},
        {"source_url": "https://example.org\\other"},
        {"source_url": "https://"},
        {"source_url": "https://@example.org"},
        {"source_url": "https:////example.org"},
        {"source_url": "https://example.org/\ud800"},
        {"source_url": "https://example.org:99999"},
        {"source_sha256": "A" * 64},
        {"source_version": ""},
        {"source_version": "   "},
        {"content_kind": "generated_gold"},
        {"unknown": "field"},
    ],
)
def test_invalid_documents_are_rejected(updates: dict[str, object]) -> None:
    """Bounded source identities cannot hide malformed URLs or ambiguous content classifications."""
    with pytest.raises(ValidationError):
        PaperDocument.model_validate({**paper("one", "text").model_dump(), **updates})


def test_duplicate_ids_forged_models_and_corpus_limits_fail() -> None:
    """Validation applies to model instances and consumes at most one record beyond the hard cap."""
    with pytest.raises(ResearchError, match="Duplicate"):
        BM25Index([paper("same", "one"), paper("same", "different")])
    with pytest.raises(ValidationError):
        BM25Index([PaperDocument.model_construct(paper_id="forged")])
    with pytest.raises(ResearchError, match="document limit"):
        BM25Index(paper(str(index), "word") for index in range(501))
    assert len(BM25Index(paper(str(index), "word") for index in range(500)).search("word")) == 10
    with pytest.raises(ResearchError, match="byte limit"):
        BM25Index(paper(str(index), "界" * 16000) for index in range(500))


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_query_limits_fail(limit: int) -> None:
    """Booleans and out-of-range/noninteger top-k requests cannot disable result bounds."""
    with pytest.raises(ResearchError):
        BM25Index([]).search("query", limit=limit)


def test_query_length_and_type_limits_fail_before_scoring() -> None:
    """Even empty indexes enforce query bounds consistently."""
    index = BM25Index([])
    assert index.search("q" * 4000) == ()
    with pytest.raises(ResearchError):
        index.search("q" * 4001)
    with pytest.raises(ResearchError):
        index.search(None)  # type: ignore[arg-type]


def test_index_is_a_snapshot_and_result_limit_twenty_is_inclusive() -> None:
    """Mutation of the caller's input list cannot change a built corpus or expand top-k output."""
    documents = [paper(f"paper-{index:02d}", "value") for index in range(21)]
    index = BM25Index(documents)
    documents.clear()
    hits = index.search("value", limit=20)
    assert len(hits) == 20 and hits[-1].document.paper_id == "paper-19"


@pytest.mark.parametrize("score", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_hits_require_finite_positive_scores(score: float) -> None:
    """Invalid scores cannot cross the typed ranking boundary."""
    with pytest.raises(ValidationError):
        LexicalHit(document=paper("one", "text"), score=score)
