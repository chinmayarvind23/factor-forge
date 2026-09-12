# Elasticsearch literature metadata search

Optional isolated environment for indexing explicit canonical `DiscoveryResult` receipts.
Each receipt is replayed against byte-verified local artifacts before writes. Documents
contain DOI/title/rank and receipt/response SHA-256 identities; full paper text, embeddings,
and admission decisions are excluded. Re-indexing uses deterministic content IDs. Different
receipts may return the same DOI as distinct provenance-bearing hits.

From the repository root:

```powershell
uv sync --project tools/search --locked
$env:FACTORFORGE_ELASTICSEARCH_URL = 'http://localhost:9200'
uv run --project tools/search python tools/search/search.py index --receipt path/to/canonical-discovery.json --artifacts artifacts
uv run --project tools/search python tools/search/search.py search --query 'momentum' --limit 10
uv run --project tools/search pytest tools/search/test_search.py -q
```

Use an Elasticsearch 9.x service. URL defaults to localhost:9200. Optional environment
variables `FACTORFORGE_ELASTICSEARCH_API_KEY` and `FACTORFORGE_ELASTICSEARCH_CA_CERTS`
configure authentication and a trusted CA. TLS verification stays enabled. Index defaults
to `factorforge-literature-v1`; place `--index factorforge-literature-NAME` before the
subcommand to override. Existing mappings must match the strict schema. Interrupted
indexing can leave a partial receipt; replaying the same command safely completes it.

Search uses title BM25 plus exact DOI matching, 1–20 hits, a bounded printable query,
no caller-supplied DSL, a five-second server search timeout and ten-second client request
timeout without retries. Search output provides metadata artifact identities for later
verification; it does not establish source rights, page evidence, or research quality.

Tests use synthetic data and the official client's transport interface. Set
`FACTORFORGE_ELASTICSEARCH_TEST_URL` to opt into an actual service smoke test; it creates
and deletes only a fresh `factorforge-literature-smoke-<uuid>` index. This checks indexing,
idempotent replay and retrieval.

API references: [official Python client getting started](https://www.elastic.co/docs/reference/elasticsearch/clients/python/getting-started)
and [client examples](https://www.elastic.co/docs/reference/elasticsearch/clients/python/examples).
