# Local evidence explorer

This isolated optional uv project exposes saved historical experiments and seven
allowlisted reports. It does not run research, retrieve data, execute code, alter
artifacts, or establish published-factor reproduction claims. Both transports use
the same bounded JSON loader and Pydantic study validation. Receipt validation
checks an object and schema version (or manifest digest map), not independent verification of its claims;
SHA-256 identifies bytes, not authenticity.

From the repository root:

```powershell
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
absolute path with your checkout):

```json
["run", "--project", "C:/path/factor_forge/tools/explorer", "--locked", "C:/path/factor_forge/tools/explorer/mcp_server.py"]
```

Tools: `study_summary`, `list_experiments(limit, offset)`, `list_evidence`,
`read_receipt(evidence_id)`. No network MCP listener or arbitrary path input is
provided. The official SDK's supported v1 maintenance line is deliberately pinned
below v2 because its FastMCP protocol contract is used here. `uv.lock` freezes all
dependencies. The smoke test launches a real SDK stdio client/server subprocess
and performs HTTP requests through ASGI, with oversized requests, invalid paths,
invalid pagination, mutations, excessive tokens, and Host rejection checks.

Official references: [Strawberry token limiter](https://strawberry.rocks/docs/extensions/max-tokens-limiter),
[depth limiter](https://strawberry.rocks/docs/extensions/query-depth-limiter),
[official MCP v1 SDK](https://py.sdk.modelcontextprotocol.io/v1/).
