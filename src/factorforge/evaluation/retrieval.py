"""Closed-corpus binary retrieval evaluation with separate answerability partitions."""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import PaperDocument
from factorforge.retrieval.lexical import BM25Index

type Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
type Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type Binary = Annotated[int, Field(ge=0, le=1)]


class _CanonicalModel(BaseModel):
    """Revalidate nested models and hash the complete canonical evaluation input."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )

    def canonical_bytes(self) -> bytes:
        """Sorting object keys preserves identity across JSON indentation and newline styles."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        """Bind all declared metadata and content rather than a display-only version label."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class RetrievalCorpus(_CanonicalModel):
    """A frozen corpus is bounded to the same capacity as the baseline index."""

    version: Identifier
    status: Literal["frozen"]
    documents: Annotated[tuple[PaperDocument, ...], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def unique_documents(self) -> Self:
        """Repeated IDs cannot overwrite one another in relevance labels or result lookup."""
        if len({document.paper_id for document in self.documents}) != len(self.documents):
            raise ValueError("Corpus document identifiers must be unique")
        if sum(len(document.canonical_bytes()) for document in self.documents) > 8 * 1024 * 1024:
            raise ValueError("Corpus exceeds its byte limit")
        return self


class JudgedQuery(_CanonicalModel):
    """Every query contains explicit binary labels for the entire closed corpus."""

    query_id: Identifier
    text: str = Field(min_length=1, max_length=4000)
    judgments: Annotated[dict[Identifier, Binary], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def meaningful_text(self) -> Self:
        """Whitespace-only query labels cannot define a meaningful evaluation case."""
        if not self.text.strip() or any(
            ord(char) < 32 and char not in "\r\n\t" for char in self.text
        ):
            raise ValueError("Query text must be meaningful and portable")
        return self


class RetrievalJudgments(_CanonicalModel):
    """Judgments bind exact corpus bytes and carry their own versioned query inventory."""

    version: Identifier
    status: Literal["frozen"]
    corpus_sha256: Digest
    queries: Annotated[tuple[JudgedQuery, ...], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def unique_queries(self) -> Self:
        """Repeated query IDs cannot conceal cases from metric denominators."""
        if len({query.query_id for query in self.queries}) != len(self.queries):
            raise ValueError("Query identifiers must be unique")
        return self


class QueryResult(_CanonicalModel):
    """Per-query evidence exposes ranks and relevance counts behind every aggregate."""

    query_id: str
    query_sha256: Digest
    returned_ids: tuple[str, ...]
    relevant_count: int
    relevant_returned: int
    recall_at_k: float | None
    reciprocal_rank_at_k: float | None


class RetrievalReport(_CanonicalModel):
    """Undefined partitions are null; the caller must not present them as perfect quality."""

    schema_version: Literal["retrieval-report-v1"] = "retrieval-report-v1"
    corpus_sha256: Digest
    qrels_sha256: Digest
    k: int
    answerable_queries: int
    no_relevant_queries: int
    recall_at_k: float | None
    mrr_at_k: float | None
    no_relevant_false_positive_rate: float | None
    no_relevant_abstention_rate: float | None
    no_relevant_returned_documents: int
    query_results: tuple[QueryResult, ...]


def _inputs(
    corpus: RetrievalCorpus, qrels: RetrievalJudgments, k: int
) -> tuple[RetrievalCorpus, RetrievalJudgments]:
    """Revalidate caller-owned nested data before comparing version identities and coverage."""
    try:
        source = RetrievalCorpus.model_validate(corpus)
        labels = RetrievalJudgments.model_validate(qrels)
        if type(k) is not int or not 1 <= k <= 20:
            raise ValueError("Invalid retrieval cutoff")
        if labels.corpus_sha256 != source.sha256:
            raise ResearchError(
                "RETRIEVAL_EVAL_INVALID", "Judgments do not match corpus identity.", 422
            )
        ids = {document.paper_id for document in source.documents}
        if any(set(query.judgments) != ids for query in labels.queries):
            raise ValueError("Every document/query pair must be judged")
        return source, labels
    except ValueError:
        raise ResearchError(
            "RETRIEVAL_EVAL_INVALID", "Retrieval evaluation inputs are invalid.", 422
        ) from None


def score_rankings(
    corpus: RetrievalCorpus,
    qrels: RetrievalJudgments,
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 3,
) -> RetrievalReport:
    """Macro-average only answerable queries and measure negative-query returns separately."""
    source, labels = _inputs(corpus, qrels, k)
    ids = {document.paper_id for document in source.documents}
    if not isinstance(rankings, Mapping) or set(rankings) != {
        query.query_id for query in labels.queries
    }:
        raise ResearchError("RETRIEVAL_EVAL_INVALID", "Ranking query inventory is incomplete.", 422)
    rows: list[QueryResult] = []
    for query in labels.queries:
        ranking = rankings[query.query_id]
        if (
            not isinstance(ranking, Sequence)
            or isinstance(ranking, (str, bytes))
            or len(ranking) > len(ids)
        ):
            raise ResearchError(
                "RETRIEVAL_EVAL_INVALID", "Ranking document inventory is invalid.", 422
            )
        ranked = tuple(ranking)
        if any(not isinstance(name, str) or name not in ids for name in ranked) or len(
            set(ranked)
        ) != len(ranked):
            raise ResearchError(
                "RETRIEVAL_EVAL_INVALID", "Ranking document inventory is invalid.", 422
            )
        returned = ranked[:k]
        relevant = sum(query.judgments.values())
        found = sum(query.judgments[name] for name in returned)
        first = next((rank for rank, name in enumerate(returned, 1) if query.judgments[name]), None)
        rows.append(
            QueryResult(
                query_id=query.query_id,
                query_sha256=query.sha256,
                returned_ids=returned,
                relevant_count=relevant,
                relevant_returned=found,
                recall_at_k=found / relevant if relevant else None,
                reciprocal_rank_at_k=(1 / first if first else 0.0) if relevant else None,
            )
        )
    recalls = [row.recall_at_k for row in rows if row.recall_at_k is not None]
    reciprocal = [row.reciprocal_rank_at_k for row in rows if row.reciprocal_rank_at_k is not None]
    negatives = [row for row in rows if row.relevant_count == 0]
    false_positives = sum(bool(row.returned_ids) for row in negatives)
    return RetrievalReport(
        corpus_sha256=source.sha256,
        qrels_sha256=labels.sha256,
        k=k,
        answerable_queries=len(recalls),
        no_relevant_queries=len(negatives),
        recall_at_k=math.fsum(recalls) / len(recalls) if recalls else None,
        mrr_at_k=math.fsum(reciprocal) / len(reciprocal) if reciprocal else None,
        no_relevant_false_positive_rate=false_positives / len(negatives) if negatives else None,
        no_relevant_abstention_rate=(len(negatives) - false_positives) / len(negatives)
        if negatives
        else None,
        no_relevant_returned_documents=sum(len(row.returned_ids) for row in negatives),
        query_results=tuple(rows),
    )


def evaluate_retrieval(
    corpus: RetrievalCorpus, qrels: RetrievalJudgments, *, k: int = 3
) -> RetrievalReport:
    """Run the fixed positive-score BM25 baseline without tuning a relevance threshold."""
    source, labels = _inputs(corpus, qrels, k)
    index = BM25Index(source.documents)
    rankings = {
        query.query_id: [hit.document.paper_id for hit in index.search(query.text, limit=k)]
        for query in labels.queries
    }
    return score_rankings(source, labels, rankings, k=k)
