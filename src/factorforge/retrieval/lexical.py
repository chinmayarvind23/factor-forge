"""Fixed local BM25 baseline: Unicode alphanumerics, exact lengths and positive Lucene IDF.

Tokenization uses casefold and [^\\W_]+: no stemming, stop-word removal or accent folding.
Title and text form one field without a title boost. Query terms are deduplicated.
IDF and defaults: https://lucene.apache.org/core/10_3_1/core/org/apache/lucene/search/
similarities/BM25Similarity.html. Conventional BM25 retains the (k1+1) numerator;
this is not a claim of bit-for-bit Lucene analyzer, norm encoding or score equivalence.
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from factorforge.domain.errors import ResearchError
from factorforge.domain.literature import LexicalHit, PaperDocument

MAX_DOCUMENTS: Final = 500
MAX_CORPUS_BYTES: Final = 8 * 1024 * 1024
MAX_QUERY_CHARACTERS: Final = 4000
K1: Final = 1.2
B: Final = 0.75


def _tokens(text: str) -> tuple[str, ...]:
    """Casefold Unicode alphanumeric runs; underscores and punctuation separate tokens."""
    return tuple(re.findall(r"[^\W_]+", text.casefold()))


@dataclass(frozen=True, slots=True, init=False)
class BM25Index:
    """An immutable bounded snapshot exposes no tuning knobs, network access or model calls."""

    _documents: tuple[PaperDocument, ...]
    _frequencies: tuple[Mapping[str, int], ...]
    _lengths: tuple[int, ...]
    _idf: Mapping[str, float]
    _average_length: float

    def __init__(self, documents: Iterable[PaperDocument]) -> None:
        """Validate and bound each record before constructing corpus statistics or accepting IDs."""
        accepted: list[PaperDocument] = []
        identifiers: set[str] = set()
        frequencies: list[Mapping[str, int]] = []
        lengths: list[int] = []
        document_frequencies: Counter[str] = Counter()
        total_bytes = 0
        for ordinal, supplied in enumerate(documents):
            if ordinal >= MAX_DOCUMENTS:
                raise ResearchError("CORPUS_TOO_LARGE", "Corpus exceeds the document limit.", 413)
            document = PaperDocument.model_validate(supplied)
            if document.paper_id in identifiers:
                raise ResearchError("DUPLICATE_PAPER_ID", "Duplicate paper identity.", 409)
            total_bytes += len(document.canonical_bytes())
            if total_bytes > MAX_CORPUS_BYTES:
                raise ResearchError("CORPUS_TOO_LARGE", "Corpus exceeds the byte limit.", 413)
            identifiers.add(document.paper_id)
            accepted.append(document)
            counts = Counter(_tokens(document.title + "\n" + document.text))
            frequencies.append(MappingProxyType(dict(counts)))
            lengths.append(sum(counts.values()))
            document_frequencies.update(counts.keys())
        size = len(accepted)
        # log1p is accurate when a frequent term's positive IDF is close to zero.
        idf = {
            term: math.log1p((size - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequencies.items()
        }
        object.__setattr__(self, "_documents", tuple(accepted))
        object.__setattr__(self, "_frequencies", tuple(frequencies))
        object.__setattr__(self, "_lengths", tuple(lengths))
        object.__setattr__(self, "_idf", MappingProxyType(idf))
        object.__setattr__(self, "_average_length", sum(lengths) / size if size else 0.0)

    def search(self, query: str, *, limit: int = 10) -> tuple[LexicalHit, ...]:
        """Return positive scores in descending order, with paper-ID ordering for exact ties."""
        if not isinstance(query, str) or len(query) > MAX_QUERY_CHARACTERS:
            raise ResearchError("INVALID_QUERY", "Query exceeds its text limit or type.", 422)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ResearchError(
                "INVALID_LIMIT", "Result limit must be an integer from 1 to 20.", 422
            )
        terms = tuple(sorted(set(_tokens(query)).intersection(self._idf)))
        if not terms:
            return ()
        hits: list[LexicalHit] = []
        for document, frequencies, length in zip(
            self._documents, self._frequencies, self._lengths, strict=True
        ):
            normalization = K1 * (1 - B + B * length / self._average_length)
            score = math.fsum(
                self._idf[term] * (frequency * (K1 + 1)) / (frequency + normalization)
                for term in terms
                if (frequency := frequencies.get(term, 0))
            )
            if score > 0:
                hits.append(LexicalHit(document=document, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.document.paper_id))
        return tuple(hits[:limit])
