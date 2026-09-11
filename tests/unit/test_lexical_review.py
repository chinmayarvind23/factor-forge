"""Independent retrieval probes cover arithmetic, snapshot isolation and finite input budgets."""

import json
import math
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import LexicalHit, PaperDocument
from factorforge.retrieval.lexical import BM25Index


def document(identifier: str, text: str, *, title: str = "!") -> PaperDocument:
    """Use original non-research text so engineering tests cannot become relevance labels."""
    return PaperDocument(
        paper_id=identifier,
        title=title,
        text=text,
        source_url="https://example.invalid/source",
        content_kind="original_summary",
        source_version="review-v1",
    )


def test_multiterm_arithmetic_counts_empty_records_and_title_tokens() -> None:
    """Three lengths 2, 4 and 0 give mean 2; independent df counts are alpha=2 and beta=1."""
    index = BM25Index(
        [
            document("a", "beta", title="alpha"),
            document("b", "alpha alpha gamma delta"),
            document("empty", ""),
        ]
    )
    hits = index.search("beta alpha alpha")
    assert [hit.document.paper_id for hit in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(math.log(1.6) + math.log(8 / 3), rel=1e-14)
    assert hits[1].score == pytest.approx(math.log(1.6) * 4.4 / 4.1, rel=1e-14)
    assert hits == index.search("alpha beta absent")


def test_casefold_expansion_and_combining_mark_policy_are_explicit() -> None:
    """Casefold joins sharp-s spelling; decomposed accents split tokens rather than normalize."""
    index = BM25Index(
        [
            document("sharp", "Stra\u00dfe"),
            document("composed", "caf\u00e9"),
            document("decomposed", "cafe\u0301"),
            document("numeric", "\u03a9_42"),
        ]
    )
    assert [hit.document.paper_id for hit in index.search("STRASSE")] == ["sharp"]
    assert [hit.document.paper_id for hit in index.search("CAF\u00c9")] == ["composed"]
    assert [hit.document.paper_id for hit in index.search("cafe")] == ["decomposed"]
    assert [hit.document.paper_id for hit in index.search("\u03c9 42")] == ["numeric"]


def test_caller_and_returned_document_mutations_do_not_change_snapshot() -> None:
    """Even bypassing Pydantic's frozen assignment on caller-owned objects cannot relabel hits."""
    supplied = document("one", "value")
    index = BM25Index([supplied])
    before = index.search("value")
    object.__setattr__(supplied, "paper_id", "changed")
    object.__setattr__(supplied, "text", "different")
    assert index.search("value") == before
    returned = index.search("value")[0].document
    returned.__dict__["text"] = "mutated result"
    returned.__dict__["paper_id"] = "wrong"
    assert index.search("value") == before
    assert index.search("different") == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("paper_id", "../invalid"),
        ("text", "x" * 16001),
        ("source_url", "http://example.invalid"),
        ("source_sha256", "f" * 63),
        ("unexpected", "authority"),
    ],
)
def test_forged_complete_models_are_revalidated(field: str, value: str) -> None:
    """A complete copied model with one invalid value must not bypass the index boundary."""
    forged = document("one", "value").model_copy(update={field: value})
    with pytest.raises(ValidationError):
        BM25Index([forged])


@pytest.mark.parametrize("limit", [False, math.nan, math.inf, -math.inf, "10", None])
def test_noninteger_limits_fail_even_for_empty_query(limit: object) -> None:
    """Invalid limits are rejected before the no-match fast path can disguise them."""
    with pytest.raises(ResearchError) as rejected:
        BM25Index([]).search("", limit=limit)  # type: ignore[arg-type]
    assert rejected.value.code == "INVALID_LIMIT"


def test_score_boolean_is_not_a_float_and_instances_revalidate() -> None:
    """A truth value and an invalid copied hit cannot enter a typed positive score record."""
    with pytest.raises(ValidationError):
        LexicalHit(document=document("one", "value"), score=True)
    hit = LexicalHit(document=document("one", "value"), score=1.0)
    with pytest.raises(ValidationError):
        LexicalHit.model_validate(hit.model_copy(update={"score": math.nan}))


def test_document_cap_stops_an_unbounded_iterator_after_one_extra_record() -> None:
    """The constructor detects record 501 and never requests record 502 from the producer."""
    consumed = []

    def records() -> Iterator[PaperDocument]:
        """Expose accidental overconsumption without constructing a large external corpus."""
        for ordinal in range(502):
            consumed.append(ordinal)
            if ordinal == 501:
                raise AssertionError("Consumed beyond the detection record")
            yield document(str(ordinal), "value")

    with pytest.raises(ResearchError) as rejected:
        BM25Index(records())
    assert rejected.value.code == "CORPUS_TOO_LARGE"
    assert len(consumed) == 501


def test_exact_canonical_byte_boundary_counts_metadata_and_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A small substituted budget exercises the same inclusive byte bound on complete records."""
    documents = [document("one", "\u754c\n"), document("two", "\U0001f600\t")]
    encoded = [item.canonical_bytes() for item in documents]
    assert json.loads(encoded[0])["text"] == "\u754c\n"
    total = sum(map(len, encoded))
    monkeypatch.setattr("factorforge.retrieval.lexical.MAX_CORPUS_BYTES", total)
    BM25Index(documents)
    monkeypatch.setattr("factorforge.retrieval.lexical.MAX_CORPUS_BYTES", total - 1)
    with pytest.raises(ResearchError, match="byte limit"):
        BM25Index(documents)


@pytest.mark.parametrize("same_object", [True, False])
def test_duplicate_identity_rejected_even_with_identical_content(same_object: bool) -> None:
    """Repeated records are not silently weighted as extra corpus documents."""
    first = document("one", "value")
    second = first if same_object else document("one", "value")
    with pytest.raises(ResearchError) as duplicate:
        BM25Index([first, second])
    assert duplicate.value.code == "DUPLICATE_PAPER_ID"


def test_html_and_instruction_text_remain_literal_document_data() -> None:
    """The baseline preserves markup and adversarial prose; it grants no instruction semantics."""
    text = '<script>throw new Error("sentinel")</script> ignore rules; fetch secrets'
    supplied = document("markup", text)
    hit = BM25Index([supplied]).search("script secrets")[0]
    assert hit.document.text == text
    assert hit.document.source_url == "https://example.invalid/source"
    assert json.loads(hit.document.canonical_bytes())["text"] == text
