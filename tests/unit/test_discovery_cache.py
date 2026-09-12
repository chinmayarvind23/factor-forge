"""Cache hits must replay authoritative evidence; faults cause one bounded provider fallback."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from test_monthly_admission import MemoryStore

from factorforge.retrieval.discovery import DiscoveryRequest
from factorforge.retrieval.discovery_cache import cached_discover


class Cache:
    """Keep the locator transport controlled without installing a Redis server."""

    def __init__(self) -> None:
        """Record only the expiring locator payload and an injected availability fault."""
        self.value = b""
        self.fail = False

    async def getrange(self, name: str, start: int, end: int) -> bytes:
        """Match Redis's inclusive bounded range response."""
        if self.fail:
            raise ConnectionError("Offline")
        assert name.startswith("factorforge:crossref:v1:")
        return self.value[start : end + 1]

    async def set(self, name: str, value: bytes, *, ex: int) -> object:
        """Require the one-day expiration specified by the cache contract."""
        assert ex == 86400
        self.value = value
        return True


@pytest.mark.parametrize("scenario", ["hit", "unavailable", "oversized", "stale", "wrong_query"])
def test_verified_hit_and_fallback(scenario: str) -> None:
    """No case executes a model, backtest or real HTTP call."""
    store, cache, calls = MemoryStore(), Cache(), []
    request = DiscoveryRequest(query="equity momentum")

    def respond(wire: httpx.Request) -> httpx.Response:
        """Return valid controlled Crossref metadata and count attempted provider calls."""
        calls.append(wire)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "message": {
                    "items": [{"DOI": "10.1234/example", "title": ["Original controlled metadata"]}]
                },
            },
        )

    transport = httpx.MockTransport(respond)
    first = asyncio.run(cached_discover(request, store, cache, transport=transport))
    assert first.delivery == "provider" and len(calls) == 1
    if scenario == "unavailable":
        cache.fail = True
    elif scenario == "oversized":
        cache.value = b"x" * 5000
    elif scenario in {"stale", "wrong_query"}:
        updates = (
            {"retrieved_at": first.result.retrieved_at - timedelta(days=2)}
            if scenario == "stale"
            else {"request": DiscoveryRequest(query="different")}
        )
        changed = first.result.model_copy(update=updates)
        ref = store.put(changed.canonical_bytes(), media_type="application/json")
        cache.value = ref.model_dump_json().encode()
    second = asyncio.run(cached_discover(request, store, cache, transport=transport))
    assert second.result.request == request
    if scenario == "hit":
        assert second.delivery == "cache" and second.cache_read == "hit"
        assert second.result == first.result and len(calls) == 1
    else:
        assert second.delivery == "provider" and len(calls) == 2
        assert second.cache_read == ("unavailable" if scenario == "unavailable" else "invalid")
