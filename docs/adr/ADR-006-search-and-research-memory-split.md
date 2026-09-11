# ADR-006: Split text retrieval, graph traversal, and vector benchmarking

## Decision

Use Elasticsearch for hybrid literature/research-text search, Neo4j for relationship traversal, and Weaviate for a vector-specific comparison path.

## Rationale

The systems solve different query shapes.

## Tradeoff

Multiple derived indexes increase operations and freshness concerns.

## Acceptance

A derived store must demonstrate measurable value. Weaviate is removable if it does not improve quality, latency, or operator simplicity enough to justify itself.

## Implementation sequence

The first implementation is an in-process BM25 baseline over immutable, versioned paper documents. It uses Unicode case-folded alphanumeric tokens, no stemming or stop-word removal, equal title/body treatment, `k1=1.2`, and `b=0.75`. Query terms are deduplicated. Equal scores sort by paper identifier so replay does not depend on ingestion order.

The index admits at most 500 documents and 8 MiB of canonical document JSON. It snapshots validated input and returns validated copies. Original summaries and source passages have separate content-kind labels; the indexed document hash is distinct from an optional upstream PDF hash.

The lexical implementation has 61 passing unit tests, including independent review tests and hand-calculated scores. Retrieval quality remains unmeasured until the pilot corpus and judgments are frozen. Elasticsearch, Neo4j, and Weaviate remain planned comparison paths; their addition must demonstrate value against this baseline.
