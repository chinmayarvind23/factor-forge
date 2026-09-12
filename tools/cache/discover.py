"""Run optional Redis-assisted literature discovery with the standard artifact store."""

import argparse
import asyncio
import os
from pathlib import Path
from typing import cast

from redis.asyncio import Redis

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.retrieval.discovery import DiscoveryRequest
from factorforge.retrieval.discovery_cache import LocatorCache, cached_discover


async def main() -> None:
    """Read cache credentials from the environment and close all client connections on exit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = DiscoveryRequest(query=args.query, limit=args.limit)
    client = Redis.from_url(
        os.environ["FACTORFORGE_REDIS_URL"],
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=False,
    )
    try:
        with args.output.open("xb") as output:
            result = await cached_discover(
                request, LocalArtifactStore(args.artifacts), cast(LocatorCache, client)
            )
            output.write(result.canonical_bytes())
        print(result.model_dump_json())
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
