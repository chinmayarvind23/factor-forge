# Literature-to-extraction handoff

`research_sources` reads the idea from an owner-verified canonical research run. It
uses the existing BM25 index to rank a supplied `LiteratureCatalog`, retains up to
20 positive-scoring hits, and sends the first three source packets to the durable
extraction worker in ranking order. No-hit queries produce an empty selection and
no provider calls. Positive lexical scores are retrieval signals, not a measured
claim that a paper is relevant.

The catalog contains at most 32 entries. Each entry pairs an indexed `PaperDocument`
with a reviewed `SourcePacket`; paper ID and source hash must agree, and paper IDs
must be unique. An indexed original summary is not passed off as a physical source
page. Extraction reads the packet's separately retained page artifacts and checks
them through its existing source-admission path. Source acquisition, permitted use
and page selection belong to trusted ingestion; catalog metadata alone does not
establish those rights or verify an upstream PDF.

Canonical catalog and selection artifacts preserve the query, ranking, source
identities and selection policy. The final `ResearchSources` artifact retains one
typed extraction outcome for every selected source. Metadata publication is bounded
to four MiB per object. The pipeline accepts no network or filesystem destination.

Each extraction has a stable run/command-derived operation identity, so deterministic
retrieval can replay while already settled model work is reused. A crash between
sources leaves completed source operations available to the next worker. A pending
operation requires reconciliation rather than an automatic duplicate call. The
per-source maximum charge remains subject to the original run's total budget.

Tests use original indexed text and controlled provider responses with actual
PostgreSQL transactions. They verify ranking-to-packet correspondence and reuse of
three saved outcomes; they do not constitute a retrieval or model-accuracy benchmark.
