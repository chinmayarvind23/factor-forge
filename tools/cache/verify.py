"""Verify actual Redis expiry and locator reuse using controlled, offline provider metadata."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import uuid4

import httpx
from redis.asyncio import Redis

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.retrieval.discovery import DiscoveryRequest
from factorforge.retrieval.discovery_cache import LocatorCache, cached_discover


async def main() -> None:
    """Use a unique key and remove only that key; never flush an operator's Redis database."""
    client = Redis.from_url(
        os.environ["FACTORFORGE_REDIS_URL"],
        decode_responses=False,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    request = DiscoveryRequest(query="FactorForge controlled transport " + uuid4().hex)
    key = "factorforge:crossref:v1:" + request.sha256
    calls = []

    def respond(wire: httpx.Request) -> httpx.Response:
        """Supply authored metadata locally; no literature provider or model is contacted."""
        calls.append(wire)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "message": {
                    "items": [
                        {"DOI": "10.1234/controlled", "title": ["Controlled integration metadata"]}
                    ]
                },
            },
        )

    try:
        await client.ping()
        info = await client.info("server")
        with TemporaryDirectory(prefix="factorforge-cache-") as temporary:
            store = LocalArtifactStore(Path(temporary))
            cache = cast(LocatorCache, client)
            transport = httpx.MockTransport(respond)
            first = await cached_discover(request, store, cache, transport=transport)
            second = await cached_discover(request, store, cache, transport=transport)
            assert first.delivery == "provider" and second.delivery == "cache"
            assert first.result == second.result and len(calls) == 1
            ttl = await client.ttl(key)
            assert 86300 <= ttl <= 86400
            await client.set(key, b"invalid locator", ex=86400)
            third = await cached_discover(request, store, cache, transport=transport)
            assert third.delivery == "provider" and third.cache_read == "invalid"
            assert len(calls) == 2
            print(
                json.dumps(
                    dict(
                        schema_version="redis-discovery-integration-v1",
                        scope="Real Redis with controlled offline provider metadata",
                        redis_version=info["redis_version"],
                        verified_cache_reuse=True,
                        observed_ttl_seconds=ttl,
                        malformed_locator_fallback=True,
                        provider_transport_calls=len(calls),
                        live_provider_calls=0,
                    )
                )
            )
    finally:
        try:
            await client.delete(key)
        finally:
            await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
