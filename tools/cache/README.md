# Redis-assisted literature discovery

Redis stores short-lived artifact locators for successful Crossref searches. The
query and result limit determine a versioned hashed cache key. Cache values contain
artifact references; the full provider response and discovery receipt remain in the
authoritative artifact store.

On a hit, FactorForge verifies the result bytes, replays candidate extraction against
the retained response, checks the exact request and accepts only successful captures
from the preceding 24 hours. Original capture timestamps remain unchanged. Missing,
oversized, malformed, stale or unavailable entries fall back to the existing bounded
Crossref request. Provider failures are not cached. Reads and writes each have a
one-second deadline; bounded `GETRANGE` limits locator transfer to 4,097 bytes.

```powershell
uv sync --project tools/cache --locked
# Configure a trusted Redis endpoint in FACTORFORGE_REDIS_URL.
uv run --project tools/cache --locked python tools/cache/discover.py --query "equity momentum" --artifacts artifacts/research --output artifacts/discovery-cached.json
```

Use an authenticated Redis deployment in the same operator trust domain as the
artifact store. The command reads credentials only from its environment. Cache
eviction cannot delete research evidence. This cache provides neither authorization
nor research locking; PostgreSQL retains those responsibilities.

Each invocation publishes a `cached-discovery-v1` receipt with the full discovery
result, cache-read status and actual `cache` or `provider` delivery path. A cache write
failure does not invalidate a captured provider result. Concurrent misses can produce
more than one search; this implementation has no distributed single-flight lock.

Five offline checks cover hits, availability faults, oversized entries, stale captures
and mismatched requests. A real Redis 7.4.11 integration run also verified cache reuse,
86,400-second expiry and malformed-locator fallback, using controlled HTTP metadata.
Its [receipt](../../reports/evidence/redis-discovery.json) records zero live provider calls.
Repeat that integration check against an operator-provided Redis endpoint with
`uv run --project tools/cache --locked python tools/cache/verify.py`.
End-to-end research runtime savings remain unmeasured.

References: [redis-py async lifecycle](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html),
[bounded GETRANGE](https://redis.io/docs/latest/commands/getrange/).
