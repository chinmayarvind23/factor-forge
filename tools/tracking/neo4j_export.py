"""Project verified research lineage into Neo4j and find runs sharing source artifacts."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from factorforge.data.artifacts import ArtifactStore, LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.lineage.closure import verify_closure


def build_projection(root: ArtifactRef, store: ArtifactStore) -> dict[str, Any]:
    """Only verified typed references become graph edges; source text never becomes Cypher."""
    refs = verify_closure(root, store)
    nodes = []
    edges = []
    for ref in refs:
        raw = store.get(ref)
        verify_bytes(raw, ref)
        value = json.loads(raw) if ref.media_type == "application/json" else None
        nodes.append(
            {
                **ref.model_dump(),
                "schema": str(value.get("schema_version", ""))[:128]
                if isinstance(value, dict)
                else "",
            }
        )
        pending = [("", value)]
        while pending:
            path, item = pending.pop()
            if isinstance(item, dict):
                if set(item) == {"sha256", "size_bytes", "media_type"}:
                    target = ArtifactRef.model_validate(item)
                    edges.append({"source": ref.sha256, "target": target.sha256, "path": path})
                else:
                    pending.extend(
                        (path + "/" + key.replace("~", "~0").replace("/", "~1"), child)
                        for key, child in item.items()
                    )
            elif isinstance(item, list):
                pending.extend((path + "/" + str(index), child) for index, child in enumerate(item))
        if len(edges) > 20000:
            raise ValueError("Graph projection exceeds edge limit")
    return {
        "root": root.sha256,
        "nodes": nodes,
        "edges": sorted(edges, key=lambda edge: (edge["source"], edge["path"], edge["target"])),
    }


def _write_and_verify(tx: Any, projection: dict[str, Any]) -> dict[str, object]:
    """Publish nodes, membership and edges atomically, then compare exact graph inventories."""
    tx.run(
        "UNWIND $nodes AS n MERGE (a:FFArtifact {sha256:n.sha256}) "
        "ON CREATE SET a.size_bytes=n.size_bytes, a.media_type=n.media_type, a.schema=n.schema",
        nodes=projection["nodes"],
    ).consume()
    tx.run(
        "MERGE (r:FFResearch {sha256:$root}) WITH r UNWIND $nodes AS n "
        "MATCH (a:FFArtifact {sha256:n.sha256}) MERGE (r)-[:CONTAINS]->(a)",
        root=projection["root"],
        nodes=projection["nodes"],
    ).consume()
    tx.run(
        "UNWIND $edges AS e MATCH (a:FFArtifact {sha256:e.source}), "
        "(b:FFArtifact {sha256:e.target}) MERGE (a)-[:REFERS_TO {path:e.path}]->(b)",
        edges=projection["edges"],
    ).consume()
    nodes = tx.run(
        "MATCH (:FFResearch {sha256:$root})-[:CONTAINS]->(a) "
        "RETURN a.sha256 AS sha256,a.size_bytes AS size_bytes,"
        "a.media_type AS media_type,a.schema AS schema ORDER BY sha256",
        root=projection["root"],
    ).data()
    edges = tx.run(
        "MATCH (r:FFResearch {sha256:$root})-[:CONTAINS]->(a)-[e:REFERS_TO]->(b) "
        "RETURN a.sha256 AS source,b.sha256 AS target,e.path AS path "
        "ORDER BY source,path,target",
        root=projection["root"],
    ).data()
    if (
        nodes != sorted(projection["nodes"], key=lambda node: node["sha256"])
        or edges != projection["edges"]
    ):
        raise ValueError("Neo4j graph differs from verified source; transaction rolled back")
    return {
        "root": projection["root"],
        "nodes": len(nodes),
        "edges": len(edges),
        "readback_verified": True,
    }


def project_graph(
    root: ArtifactRef, store: ArtifactStore, driver: Any, database: str = "neo4j"
) -> dict[str, object]:
    """Merge content identities under unique constraints; reruns retain the same graph."""
    projection = build_projection(root, store)
    for label in ("FFArtifact", "FFResearch"):
        driver.execute_query(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (a:{label}) REQUIRE a.sha256 IS UNIQUE",
            database_=database,
        )
    with driver.session(database=database) as session:
        result: dict[str, object] = session.execute_write(_write_and_verify, projection)
    return result


def related_research(source_sha256: str, driver: Any, database: str = "neo4j") -> list[str]:
    """Locate up to 100 imported research roots sharing a known verified artifact identity."""
    records, _, _ = driver.execute_query(
        "MATCH (r:FFResearch)-[:CONTAINS]->(:FFArtifact {sha256:$sha}) "
        "RETURN r.sha256 AS root ORDER BY root LIMIT 100",
        sha=source_sha256,
        database_=database,
    )
    return [str(record["root"]) for record in records]


def main() -> None:
    """Read credentials from environment; graph projection contains metadata and links only."""
    from neo4j import GraphDatabase

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    with args.root.open("rb") as source:
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError("Root reference exceeds limit")
    root = ArtifactRef.model_validate_json(raw)
    with (
        args.receipt.open("x", encoding="utf-8") as output,
        GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]),
            connection_timeout=10,
            max_transaction_retry_time=10,
        ) as driver,
    ):
        driver.verify_connectivity()
        receipt = project_graph(root, LocalArtifactStore(args.artifacts), driver)
        receipt["related_research"] = related_research(root.sha256, driver)
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
