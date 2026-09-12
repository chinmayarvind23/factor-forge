# Sources and data

FactorForge keeps a source's identity, its availability time and its execution role explicit.
A downloaded paper or data file is not automatically admitted for every use.

## Literature

[Discovery](../src/factorforge/retrieval/discovery.py) captures Crossref metadata as a
retained response. [PDF ingestion](../src/factorforge/retrieval/) prepares reviewed pages
with physical-page references. Source selection operates on a catalog that ties each
page to its document and source identity.

Elasticsearch provides [metadata search](../tools/search/README.md); Redis provides an
[expiring discovery cache](../tools/cache/README.md). Metadata lookup does not itself
authorize full-text downloading or establish a paper's strategy specification.

## Market inputs

[Dataset contracts](../src/factorforge/domain/datasets.py) and
[monthly admission](../src/factorforge/backtests/admission.py) bind the source inventory,
content hashes, rights and timing evidence. Raw prices, corporate actions, historical
membership, comparison intervals and borrowing grants have distinct roles.

Known-at timestamps govern selection. An event's economic effect and payment can occur
at different times. A short position requires an explicit active loan grant. Do not infer
historical membership or availability from a current vendor export.

[Polars source assembly](../src/factorforge/data/monthly_signals.py) builds formation inputs.
[PySpark materialization](../tools/spark/README.md) offers a separate panel transformation.
[Kafka replay](../tools/streaming/README.md) transports admitted archived observations.

## Artifacts and storage

Store source bytes, transformations and generated objects in a persistent artifact directory.
Content hashes identify objects and closure verification checks referenced bytes. Keep execution
outputs under an operator-selected directory such as `artifacts/reports`.

[MLflow and Neo4j tools](../tools/tracking/README.md) provide inspection views.
[GraphQL and MCP](../tools/explorer/README.md) use `FACTORFORGE_REPORTS_DIR` for their
operator-supplied report catalog. [Grafana](../tools/observability/README.md) reads the
file specified by `FACTORFORGE_STUDY_REPORT`.
