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

## Strategy publication

`research_strategies` composes this source stage with the
[monthly strategy compiler](source-strategy.md). Reviewed bindings pair the exact
source packet with an explicit execution environment and formation-rule text.
The coordinator rejects duplicate bindings and packets that differ from the
catalog before any provider call. A binding therefore applies to the selected
strategy and physical page references, as well as the paper version.

Each selected source produces one ordered candidate: `compiled`, `needs_review`,
`unbound` or `source_unavailable`. Both executable and unresolved compiler drafts
are published as canonical artifacts. The source extraction record is included
in the environment's source references before compilation; all existing references
remain. Environments need capacity for that additional reference within the raw
contract's 32-reference limit. The stage publishes its complete source inventory,
reviewed bindings, candidates and draft references with a four-MiB object limit.

The coordinator always obtains observations through the owner-bound extraction
worker. Replays recover settled worker results before deterministic compilation.
It does not accept an arbitrary client-supplied extraction result as worker evidence.
Published draft references identify the complete compiler request and result;
they do not prove that the source interpretation is correct. A caller can pass
a compiled strategy to the existing monthly worker with explicit capital and
evaluation time. The [experiment scheduler](research-experiments.md) now performs
that handoff through persisted monthly graphs for all compiled candidates.
