"""Discovery retains remote metadata without admitting it as physical source evidence."""

import asyncio
import json

import httpx
import pytest
from test_monthly_admission import MemoryStore

from factorforge.domain.errors import ResearchError
from factorforge.retrieval.discovery import DiscoveryRequest, discover, replay


@pytest.mark.parametrize("mode", ["ok", "duplicate", "malformed", "redirect", "rate_limit"])
def test_discovery_capture_and_offline_replay(mode: str) -> None:
    """Every terminal response is retained and replay cannot issue another network request."""
    store = MemoryStore()
    item = {"DOI": "10.1234/test", "title": ["Equity momentum"], "score": 12.5}
    payload = {
        "status": "ok",
        "message": {"items": [item, item] if mode == "duplicate" else [item]},
    }
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        """The only request must target the fixed metadata endpoint with bounded rows."""
        calls.append(request)
        assert request.url.host == "api.crossref.org"
        assert request.url.params["rows"] == "5"
        assert request.url.params["query.bibliographic"] == "equity momentum"
        return httpx.Response(
            302 if mode == "redirect" else 429 if mode == "rate_limit" else 200,
            content=b"invalid" if mode == "malformed" else json.dumps(payload).encode(),
            headers={"location": "http://127.0.0.1/private"},
        )

    result = asyncio.run(
        discover(
            DiscoveryRequest(query="equity momentum", limit=5),
            store,
            transport=httpx.MockTransport(handle),
        )
    )
    assert len(calls) == 1
    assert replay(result, store) == result
    store.values[result.response.sha256] = b"changed"
    with pytest.raises(ResearchError):
        replay(result, store)
    assert result.response is not None
    assert result.status == (
        "success"
        if mode in {"ok", "duplicate"}
        else "invalid_response"
        if mode == "malformed"
        else "http_error"
    )
    assert len(result.candidates) == (1 if mode in {"ok", "duplicate"} else 0)
    if result.candidates:
        assert result.candidates[0].doi == "10.1234/test"
        assert result.candidates[0].source_admission == "metadata_only"


def test_oversized_response_and_corrupt_capture() -> None:
    """Oversized data is a bounded partial capture and changed bytes fail replay."""
    store = MemoryStore()
    result = asyncio.run(
        discover(
            DiscoveryRequest(query="equity momentum"),
            store,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * (2**20 + 1))
            ),
        )
    )
    assert result.status == "response_too_large"
    assert result.response is not None and result.response.size_bytes == 2**20
    assert not result.capture_complete
    assert replay(result, store) == result


def test_blank_query_rejected() -> None:
    """A blank idea cannot consume a discovery request."""
    with pytest.raises(ValueError):
        DiscoveryRequest(query="   ")


def test_transport_failure_is_retained() -> None:
    """A failed connection produces a replayable terminal receipt with zero candidates."""

    def fail(request: httpx.Request) -> httpx.Response:
        """Exercise the actual transport exception path without a live service dependency."""
        raise httpx.ConnectError("offline", request=request)

    store = MemoryStore()
    result = asyncio.run(
        discover(DiscoveryRequest(query="momentum"), store, transport=httpx.MockTransport(fail))
    )
    assert result.status == "transport_error"
    assert result.candidates == () and not result.capture_complete
    assert replay(result, store) == result
