# ADR-006: Split text retrieval, graph traversal, and vector benchmarking

## Decision

Use Elasticsearch for hybrid literature/research-text search, Neo4j for relationship traversal, and Weaviate for a vector-specific comparison path.

## Rationale

The systems solve different query shapes.

## Tradeoff

Multiple derived indexes increase operations and freshness concerns.

## Acceptance

A derived store must demonstrate measurable value. Weaviate is removable if it does not improve quality, latency, or operator simplicity enough to justify itself.
