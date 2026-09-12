"""Transport smoke checks and optional real Elasticsearch indexing, never research evals."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from uuid import uuid4

import httpx
import pytest
from elastic_transport import ApiResponseMeta, BaseNode, HttpHeaders
from elastic_transport._node import NodeApiResponse
from elasticsearch import Elasticsearch
from search import MAPPINGS, documents, ingest, search

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.retrieval.discovery import DiscoveryRequest, discover


@pytest.fixture
def tmp_path():
    """Avoid unsupported Windows pytest junction cleanup with an ordinary temporary directory."""
    with TemporaryDirectory(prefix="factorforge-search-") as directory:
        yield Path(directory)


class RecordingNode(BaseNode):
    """Exercise official-client HTTP serialization without claiming server behavior."""

    requests: ClassVar[list] = []

    def perform_request(self, method, target, body=None, headers=None, request_timeout=None):
        """Record transport requests and return a minimal Elasticsearch response."""
        self.requests.append((method, target, json.loads(body) if body else None))
        metadata = ApiResponseMeta(
            200,
            "1.1",
            HttpHeaders({"x-elastic-product": "Elasticsearch", "content-type": "application/json"}),
            0,
            self.config,
        )
        return NodeApiResponse(metadata, b'{"timed_out":false,"hits":{"hits":[]}}')


def capture(tmp_path):
    """Create a synthetic retained DOI capture through the production discovery boundary."""
    store = LocalArtifactStore(tmp_path / "artifacts")

    def respond(request):
        """Return synthetic transport metadata with no external literature request."""
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "message": {
                    "items": [
                        {"DOI": "10.1234/smoke", "title": ["Synthetic momentum transport fixture"]}
                    ]
                },
            },
        )

    result = asyncio.run(
        discover(DiscoveryRequest(query="momentum"), store, transport=httpx.MockTransport(respond))
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(result.canonical_bytes())
    return store, receipt, result


def test_transport_and_bounds():
    """Verify official-client request shape and rejection before remote query dispatch."""
    RecordingNode.requests.clear()
    with Elasticsearch("http://localhost:9200", node_class=RecordingNode) as client:
        assert search(client, "factorforge-literature-test", "momentum", 3)["hits"] == []
        body = RecordingNode.requests[-1][2]
        assert body["size"] == 3
        assert body["query"]["bool"]["should"][0] == {"match": {"title": "momentum"}}
        for query, limit in [(" ", 1), ("x", 21), ("x", True)]:
            with pytest.raises(ValueError):
                search(client, "factorforge-literature-test", query, limit)
        assert len(RecordingNode.requests) == 1


def test_replay_rejects_tampering(tmp_path):
    """Reject canonical receipts whose candidates disagree with retained capture bytes."""
    store, receipt, result = capture(tmp_path)
    rows = documents(receipt, store)
    assert rows[0]["response_sha256"] == result.response.sha256
    assert set(rows[0]) == set(MAPPINGS["properties"])
    altered = result.model_copy(update={"candidates": ()})
    receipt.write_bytes(altered.canonical_bytes())
    with pytest.raises(ValueError, match="differs"):
        documents(receipt, store)


@pytest.mark.skipif(not os.getenv("FACTORFORGE_ELASTICSEARCH_TEST_URL"), reason="opt-in service")
def test_real_service(tmp_path):
    """Index and retrieve synthetic metadata on an explicitly configured actual service."""
    store, receipt, _ = capture(tmp_path)
    index = "factorforge-literature-smoke-" + uuid4().hex
    with Elasticsearch(os.environ["FACTORFORGE_ELASTICSEARCH_TEST_URL"], max_retries=0) as client:
        try:
            first = ingest(client, index, receipt, store)
            assert ingest(client, index, receipt, store) == first
            hits = search(client, index, "momentum")["hits"]
            assert len(hits) == 1
            assert hits[0]["document_id"] == first["document_ids"][0]
            assert hits[0]["source_admission"] == "metadata_only"
        finally:
            client.indices.delete(index=index, ignore_unavailable=True)
