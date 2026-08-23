# ADR-004: PostgreSQL is authoritative; Neo4j is derived research memory

## Context

Run state and lineage need transactional integrity. Research relationships benefit from graph traversal.

## Decision

Store authoritative application state in PostgreSQL. Project verified entities and relationships into Neo4j.

## Tradeoff

The graph can lag canonical state.

## Consistency

Run state is current. Graph memory is eventually consistent and rebuildable.

## Switch condition

Move authoritative data into a graph store only if transactional graph operations become the dominant workload and the integrity model remains clear.
