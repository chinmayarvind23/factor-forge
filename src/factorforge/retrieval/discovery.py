"""Bounded Crossref discovery retains replayable metadata before source admission."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import Field, field_validator

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.domain.factors import Contract
from factorforge.retrieval.selection import _publish

_ENDPOINT = "https://api.crossref.org/works"
_LIMIT = 2**20


class DiscoveryRequest(Contract):
    """An idea grants one fixed-host metadata search, without source-download permission."""

    schema_version: Literal["literature-discovery-request-v1"] = "literature-discovery-request-v1"
    query: Annotated[str, Field(min_length=1, max_length=1000)]
    limit: Annotated[int, Field(ge=1, le=20)] = 10

    @field_validator("query")
    @classmethod
    def meaningful_query(cls, value: str) -> str:
        """Reject empty and control-bearing queries before reaching the remote endpoint."""
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Discovery needs a nonblank printable query")
        return value


class PaperCandidate(Contract):
    """DOI and title identify a candidate; they do not establish text rights or page evidence."""

    doi: Annotated[str, Field(min_length=4, max_length=256, pattern=r"^10\.\d{4,9}/\S+$")]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    rank: Annotated[int, Field(ge=1, le=20)]
    source_admission: Literal["metadata_only"] = "metadata_only"


class DiscoveryResult(Contract):
    """Capture identity makes ranked discovery reproducible without repeating a live search."""

    schema_version: Literal["literature-discovery-result-v1"] = "literature-discovery-result-v1"
    request: DiscoveryRequest
    retrieved_at: datetime
    endpoint: Literal["https://api.crossref.org/works"] = "https://api.crossref.org/works"
    status: Literal[
        "success", "http_error", "invalid_response", "transport_error", "response_too_large"
    ]
    http_status: int | None
    response: ArtifactRef
    capture_complete: bool
    candidates: Annotated[tuple[PaperCandidate, ...], Field(max_length=20)]


def _candidates(raw: bytes, limit: int) -> tuple[PaperCandidate, ...]:
    """Preserve provider ordering, deduplicate DOI identities, and reject malformed records."""
    payload = json.loads(raw)
    if payload["status"] != "ok":
        raise ValueError("Remote response was not successful")
    items = payload["message"]["items"]
    if not isinstance(items, list) or len(items) > limit:
        raise ValueError("Remote inventory exceeds the request")
    result = []
    seen = set()
    for rank, item in enumerate(items, 1):
        titles = item["title"]
        if not isinstance(titles, list) or not titles:
            raise ValueError("Remote title is missing")
        candidate = PaperCandidate(doi=item["DOI"], title=titles[0], rank=rank)
        if candidate.doi.lower() not in seen:
            result.append(candidate)
            seen.add(candidate.doi.lower())
    return tuple(result)


def _interpret(
    raw: bytes, status: int | None, complete: bool, failure: str | None, request: DiscoveryRequest
) -> tuple[str, tuple[PaperCandidate, ...]]:
    """Transport and capture failures take precedence over any parseable partial payload."""
    if failure:
        return failure, ()
    if not complete:
        raise ValueError("Incomplete capture needs an explicit failure")
    if status != 200:
        return "http_error", ()
    try:
        return "success", _candidates(raw, request.limit)
    except (ValueError, TypeError, KeyError, IndexError):
        return "invalid_response", ()


async def discover(
    request: DiscoveryRequest,
    store: ArtifactStore,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DiscoveryResult:
    """One serial search has a 30-second deadline, one-MiB capture, and no redirects or retries."""
    request = DiscoveryRequest.model_validate(request)
    captured = bytearray()
    status = None
    failure = None
    complete = False
    at = datetime.now(UTC)
    try:
        async with (
            asyncio.timeout(30),
            httpx.AsyncClient(
                transport=transport,
                timeout=15,
                follow_redirects=False,
                trust_env=False,
                headers={
                    "User-Agent": "FactorForge/0.1 (https://github.com/chinmayarvind23/factor-forge)",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as client,
            client.stream(
                "GET",
                _ENDPOINT,
                params={
                    "query.bibliographic": request.query,
                    "rows": request.limit,
                    "select": "DOI,title",
                },
            ) as response,
        ):
            status = response.status_code
            async for chunk in response.aiter_bytes(chunk_size=65536):
                remaining = _LIMIT - len(captured)
                captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    failure = "response_too_large"
                    break
            else:
                complete = True
    except (httpx.HTTPError, TimeoutError):
        failure = "transport_error"
    raw = bytes(captured)
    ref = store.put(raw, media_type="text/plain")
    verify_bytes(raw, ref)
    outcome, candidates = _interpret(raw, status, complete, failure, request)
    result = DiscoveryResult.model_validate(
        dict(
            request=request,
            retrieved_at=at,
            status=outcome,
            http_status=status,
            response=ref,
            capture_complete=complete,
            candidates=candidates,
        )
    )
    _publish(store, result)
    return result


def replay(result: DiscoveryResult, store: ArtifactStore) -> DiscoveryResult:
    """Rebuild candidate metadata from verified capture bytes without network or model access."""
    result = DiscoveryResult.model_validate(result)
    raw = store.get(result.response)
    verify_bytes(raw, result.response)
    failure = result.status if result.status in {"transport_error", "response_too_large"} else None
    status, candidates = _interpret(
        raw,
        result.http_status,
        result.capture_complete,
        failure,
        result.request,
    )
    if status != result.status or candidates != result.candidates:
        raise ValueError("Discovery receipt differs from captured response")
    return result


def main() -> None:
    """Write an exclusive receipt for either one live idea search or an offline verified replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--replay", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = LocalArtifactStore(args.artifacts)
    with args.output.open("xb") as output:
        if args.replay:
            with args.replay.open("rb") as source:
                raw = source.read(_LIMIT + 1)
            if len(raw) > _LIMIT:
                raise ValueError("Replay receipt exceeds limit")
            result = replay(DiscoveryResult.model_validate_json(raw), store)
        else:
            result = asyncio.run(
                discover(DiscoveryRequest(query=args.query, limit=args.limit), store)
            )
        output.write(result.canonical_bytes())
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
