# Neo4j provenance projection

The graph adapter reads a verified artifact closure and stores content identities,
metadata and JSON-pointer reference edges. It provides reverse lookup of research
roots sharing an artifact. The original artifact store remains authoritative.

Verified against Neo4j Community 2026.08.1: 62 research artifact nodes and 295
reference edges matched readback. Repeated imports, shared-artifact lookup, bound
query parameters and rollback on conflicting metadata passed. The expanded Python
environment audit completed through OSV: 110 dependencies, no reported vulnerabilities
and no skipped packages. See the [runtime receipt](../../data/verification/neo4j-v1/receipt.json).

## Setup and usage

Use a private Neo4j Community instance. The official
[Docker guide](https://neo4j.com/docs/operations-manual/current/docker/introduction/)
describes installation and authentication. Bind local test ports to loopback, use a
unique password and set memory/CPU limits. No enterprise license or paid cloud service
is required by this adapter.

```powershell
uv sync --project tools/tracking --locked
uv run --project tools/tracking --locked pip-audit
# Configure NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD in your local environment.
uv run --project tools/tracking --locked python tools/tracking/neo4j_export.py --root source-reference.json --artifacts artifacts/research --receipt graph-receipt.json
```

`source-reference.json` contains the existing `ArtifactRef` fields: `sha256`,
`size_bytes`, `media_type`. The default URI is `bolt://127.0.0.1:7687`. Credentials
come from environment variables and are not stored in the exported receipt.

## Graph and query

`FFResearch` identifies the imported root. `CONTAINS` links it to each reachable
`FFArtifact`. Artifacts retain SHA-256, size, media type and schema version.
`REFERS_TO` links artifacts using an RFC 6901 JSON pointer identifying the reference
inside the source object. Plain strings containing a hash do not create relationships.

The adapter creates unique SHA-256 constraints, merges the graph in one managed
transaction, then compares every imported node and outgoing edge against the verified
inventory before commit. Conflicting metadata or extra edges reject the transaction.
Repeated imports use the same content identities; the real server check confirmed
identical receipts and graph inventories after replay.

```cypher
MATCH (r:FFResearch)-[:CONTAINS]->(a:FFArtifact {sha256: $source_sha256})
RETURN r.sha256 ORDER BY r.sha256 LIMIT 100
```

The Python `related_research` helper exposes this query with bound parameters. The
graph contains metadata and references, not executable source instructions. It is a
provenance lookup, not a learned strategy-selection or semantic retrieval policy.
The [official Python driver manual](https://neo4j.com/docs/python-manual/current/)
describes connectivity, parameters and managed transactions.


## Verify a disposable instance

`verify_neo4j.py` requires an empty database and the same environment credentials.
It imports the research root, repeats the import, adds a synthetic wrapper for shared
lookup, deliberately changes one metadata value, and checks transaction rollback.
It restores that value and verifies the original projection again. Use an isolated
test instance and a copy of the artifact store: the command retains two synthetic
wrapper objects locally. They do not count as additional research runs.

```powershell
uv run --project tools/tracking --locked python tools/tracking/verify_neo4j.py --root source-reference.json --artifacts artifacts/test-copy --receipt verification.json
```

The recorded instance used two CPUs, 1536 MiB RAM and a randomly assigned loopback
Bolt port. It was stopped and removed after verification. The Community image was
retrieved through `mirror.gcr.io/library/neo4j` at digest
`sha256:7f2c38fa0de8caf875d35237fa7dabda74de4f4fc2fc7c3c9e4b53c2add268ad`.
The separate Python dependency check used `pip-audit --vulnerability-service osv`;
it does not constitute a container vulnerability scan.
