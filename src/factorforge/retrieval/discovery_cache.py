"""Cache discovery artifact locators while keeping verified source bytes authoritative."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import httpx

from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.retrieval.discovery import DiscoveryRequest, DiscoveryResult, discover, replay
from factorforge.retrieval.selection import _publish


class LocatorCache(Protocol):
    """Only bounded locator reads and expiring writes are required from Redis."""

    async def getrange(self, name: str, start: int, end: int) -> bytes:
        """Read a bounded prefix; oversized or malformed values are cache misses."""
        ...

    async def set(self, name: str, value: bytes, *, ex: int) -> object:
        """Expire locators; canonical research evidence remains in the artifact store."""
        ...


class CachedDiscovery(Contract):
    """Retain the original provider timestamp and disclose the delivery path separately."""

    schema_version: Literal["cached-discovery-v1"] = "cached-discovery-v1"
    result: DiscoveryResult
    delivery: Literal["cache", "provider"]
    cache_read: Literal["hit", "miss", "invalid", "unavailable"]


async def cached_discover(
    request: DiscoveryRequest,
    store: ArtifactStore,
    cache: LocatorCache,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CachedDiscovery:
    """Use only recent, source-replayed successful results; cache failures fall back once."""
    request = DiscoveryRequest.model_validate(request)
    key = "factorforge:crossref:v1:" + request.sha256
    read: Literal["hit", "miss", "invalid", "unavailable"] = "miss"
    locator = b""
    try:
        async with asyncio.timeout(1):
            locator = await cache.getrange(key, 0, 4096)
    except Exception:
        read = "unavailable"
    if locator:
        try:
            if len(locator) > 4096:
                raise ValueError("Cached locator exceeds limit")
            ref = ArtifactRef.model_validate_json(locator)
            if ref.media_type != "application/json" or ref.size_bytes > 65536:
                raise ValueError("Invalid cached discovery metadata")
            raw = store.get(ref)
            verify_bytes(raw, ref)
            saved = replay(DiscoveryResult.model_validate_json(raw), store)
            now = datetime.now(UTC)
            if (
                saved.request != request
                or saved.status != "success"
                or saved.retrieved_at.tzinfo is None
                or not now - timedelta(hours=24) <= saved.retrieved_at <= now
            ):
                raise ValueError("Cached result is stale or belongs to another request")
            result = CachedDiscovery(result=saved, delivery="cache", cache_read="hit")
            _publish(store, result)
            return result
        except Exception:
            read = "invalid"
    fetched = await discover(request, store, transport=transport)
    if fetched.status == "success":
        ref = _publish(store, fetched)
        try:
            async with asyncio.timeout(1):
                await cache.set(key, ref.model_dump_json().encode(), ex=86400)
        except Exception:
            pass
    result = CachedDiscovery(result=fetched, delivery="provider", cache_read=read)
    _publish(store, result)
    return result
