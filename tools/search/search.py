"""Index verified discovery metadata and run bounded Elasticsearch BM25 searches."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from elasticsearch import Elasticsearch

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.retrieval.discovery import DiscoveryRequest, DiscoveryResult, replay

MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "doi": {"type": "keyword"},
        "title": {"type": "text", "similarity": "BM25"},
        "rank": {"type": "integer"},
        "receipt_sha256": {"type": "keyword"},
        "response_sha256": {"type": "keyword"},
        "source_admission": {"type": "keyword"},
    },
}


def index_name(value: str) -> str:
    """Restrict all operations to one explicitly named application index."""
    if not re.fullmatch(r"factorforge-literature-[a-z0-9][a-z0-9-]{0,100}", value):
        raise ValueError("Index must start with factorforge-literature- and use lowercase names")
    return value


def connect() -> Elasticsearch:
    """Use environment configuration with TLS verification and finite request deadlines."""
    options = {"request_timeout": 10, "max_retries": 0, "retry_on_timeout": False}
    if os.getenv("FACTORFORGE_ELASTICSEARCH_API_KEY"):
        options["api_key"] = os.environ["FACTORFORGE_ELASTICSEARCH_API_KEY"]
    if os.getenv("FACTORFORGE_ELASTICSEARCH_CA_CERTS"):
        options["ca_certs"] = os.environ["FACTORFORGE_ELASTICSEARCH_CA_CERTS"]
    return Elasticsearch(
        os.getenv("FACTORFORGE_ELASTICSEARCH_URL", "http://localhost:9200"), **options
    )


def documents(path: Path, store: ArtifactStore) -> list[dict]:
    """Replay exact retained response bytes before deriving metadata-only documents."""
    with path.open("rb") as source:
        raw = source.read(2**20 + 1)
    if len(raw) > 2**20:
        raise ValueError("Discovery receipt exceeds one MiB")
    result = DiscoveryResult.model_validate_json(raw)
    if raw != result.canonical_bytes():
        raise ValueError("Discovery receipt must use canonical bytes")
    replay(result, store)
    if result.status != "success" or not result.capture_complete:
        raise ValueError("Only successful complete discovery captures can be indexed")
    ref = store.put(raw, media_type="application/json")
    verify_bytes(store.get(ref), ref)
    return [
        {
            "doi": candidate.doi,
            "title": candidate.title,
            "rank": candidate.rank,
            "receipt_sha256": ref.sha256,
            "response_sha256": result.response.sha256,
            "source_admission": "metadata_only",
        }
        for candidate in result.candidates
    ]


def ingest(client: Elasticsearch, index: str, path: Path, store: ArtifactStore) -> dict:
    """Verify the whole receipt before writes, then idempotently index content identities."""
    index = index_name(index)
    rows = documents(path, store)
    if not client.indices.exists(index=index):
        client.indices.create(index=index, mappings=MAPPINGS)
    else:
        mapping = client.indices.get_mapping(index=index)[index]["mappings"]
        if mapping != MAPPINGS:
            raise ValueError("Existing index mapping differs from the metadata contract")
    identities = []
    for row in rows:
        identity = hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        client.index(index=index, id=identity, document=row, refresh="wait_for")
        identities.append(identity)
    return {"index": index, "indexed": len(rows), "document_ids": identities}


def search(client: Elasticsearch, index: str, query: str, limit: int = 10) -> dict:
    """Search titles with BM25 and exact DOI matching; never accept executable query DSL."""
    request = DiscoveryRequest(query=query, limit=limit)
    response = client.search(
        index=index_name(index),
        query={
            "bool": {
                "should": [
                    {"match": {"title": request.query}},
                    {"term": {"doi": request.query}},
                ],
                "minimum_should_match": 1,
            }
        },
        size=request.limit,
        source=list(MAPPINGS["properties"]),
        timeout="5s",
        track_total_hits=False,
        allow_partial_search_results=False,
    )
    if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
        raise RuntimeError("Elasticsearch search was incomplete")
    return {
        "backend": "elasticsearch-bm25-metadata-v1",
        "query": request.query,
        "hits": [
            {"document_id": hit["_id"], "score": hit["_score"], **hit["_source"]}
            for hit in response["hits"]["hits"]
        ],
    }


def main() -> None:
    """Expose explicit local receipt indexing and bounded metadata search as JSON CLI calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="factorforge-literature-v1")
    commands = parser.add_subparsers(dest="command", required=True)
    indexing = commands.add_parser("index")
    indexing.add_argument("--receipt", type=Path, required=True)
    indexing.add_argument("--artifacts", type=Path, required=True)
    querying = commands.add_parser("search")
    querying.add_argument("--query", required=True)
    querying.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    with connect() as client:
        if args.command == "index":
            result = ingest(client, args.index, args.receipt, LocalArtifactStore(args.artifacts))
        else:
            result = search(client, args.index, args.query, args.limit)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
