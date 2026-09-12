# Local evidence explorer

This isolated optional uv project exposes operator-provided study reports through
GraphQL and MCP. Both read-only transports use a bounded JSON loader and Pydantic
study validation. Receipt validation checks an object and schema version or a manifest
digest map. Hashes identify content; source admission remains a separate workflow.

From the repository root:

```powershell
# Set an absolute path to your report directory before starting either transport.
$env:FACTORFORGE_REPORTS_DIR = 'C:/path/to/reports'
uv sync --project tools/explorer --locked
uv run --project tools/explorer --locked tools/explorer/selftest.py
uv run --project tools/explorer --locked tools/explorer/graphql_server.py
```

POST JSON to `http://127.0.0.1:8765/graphql/`:

```json
{"query":"{ studySummary experiments(limit: 5) { signal costBps annualizedSharpe } evidenceIds receipt(evidenceId: \"historical-mlflow\") }"}
```

GraphQL has no mutation/subscription schema, caps depth at 4, tokens at 500,
request bodies/query strings at 16 KiB, and experiment pages at 100. The CLI binds
only loopback and validates Host. This is a local developer process; do not place
it behind a public proxy or run it on an external bind without an authentication
and deployment review. Report text remains untrusted evidence, never instructions.

For an MCP host, configure its stdio command as `uv` with arguments (replace the
absolute path with your checkout). Set `FACTORFORGE_REPORTS_DIR` in the MCP host
environment as well:

```json
["run", "--project", "C:/path/factor_forge/tools/explorer", "--locked", "C:/path/factor_forge/tools/explorer/mcp_server.py"]
```

Tools: `study_summary`, `list_experiments(limit, offset)`, `list_evidence`,
`read_receipt(evidence_id)`. No network MCP listener or arbitrary path input is
provided. The official SDK's supported v1 maintenance line is deliberately pinned
below v2 because its FastMCP protocol contract is used here. `uv.lock` freezes all
dependencies. The self-test launches a real SDK stdio client/server subprocess
and performs HTTP requests through ASGI, with oversized requests, invalid paths,
invalid pagination, mutations, excessive tokens, and Host rejection checks.

Official references: [Strawberry token limiter](https://strawberry.rocks/docs/extensions/max-tokens-limiter),
[depth limiter](https://strawberry.rocks/docs/extensions/query-depth-limiter),
[official MCP v1 SDK](https://py.sdk.modelcontextprotocol.io/v1/).
