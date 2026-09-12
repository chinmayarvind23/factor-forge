# Optional research services

These integrations are local operator tools, each with an explicit data boundary:

| Service | Input and output | Setup |
|---|---|---|
| GraphQL | Allowlisted saved evidence to bounded read queries | [Explorer](../tools/explorer/README.md) |
| MCP | The same evidence through official SDK stdio tools | [Explorer](../tools/explorer/README.md) |
| Elasticsearch | Verified discovery captures to BM25 metadata search | [Search](../tools/search/README.md) |
| Kafka | Admitted archived quotes to acknowledged transport and durable consumer journal | [Streaming](../tools/streaming/README.md) |
| Grafana / Prometheus | Saved study gauges plus current scrape health | [Monitoring](../tools/observability/README.md) |

GraphQL and MCP share a fixed evidence catalog. They cannot execute research or load
arbitrary paths. Elasticsearch returns DOI/title metadata and source identities; page
admission and rights checks still happen separately. Kafka retains original observation
clocks, validates canonical source-bound events and acknowledges consumer offsets after
durable storage. None of these services grants trading capabilities.

Grafana provisions its Prometheus source and five panels from checked-in files. Historical
results are explicitly labeled as retained gauges; scrape health is a separate live series.
The optional service environments are locked independently of the core research runtime.
The free Hugging Face Space remains a static evidence dashboard.
