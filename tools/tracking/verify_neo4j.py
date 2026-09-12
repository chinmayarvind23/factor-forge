"""Exercise graph import, replay, lookup and rollback against an empty local test database."""

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase
from neo4j_export import project_graph, related_research

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.artifacts import ArtifactRef


def main() -> None:
    """Require an empty database before controlled metadata corruption; retain a test receipt.

    This command is for an isolated disposable instance, not a production graph. The
    synthetic wrapper tests shared-artifact lookup and is not another research run.
    """
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
    store = LocalArtifactStore(args.artifacts)
    with (
        args.receipt.open("x", encoding="utf-8") as output,
        GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
            connection_timeout=10,
            max_transaction_retry_time=10,
        ) as driver,
    ):
        driver.verify_connectivity()
        records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS count")
        if records[0]["count"] != 0:
            raise ValueError("Verification requires an empty disposable database")
        first = project_graph(root, store, driver)
        repeated = project_graph(root, store, driver)
        if repeated != first:
            raise ValueError("Repeated import changed the projection receipt")
        wrapper = store.put(
            json.dumps({"verification_wrapper": root.model_dump()}).encode(),
            media_type="application/json",
        )
        second = project_graph(wrapper, store, driver)
        related = related_research(root.sha256, driver)
        if related != sorted([root.sha256, wrapper.sha256]):
            raise ValueError("Shared-artifact lookup did not return both roots")
        if related_research("' OR true RETURN 1 //", driver):
            raise ValueError("Lookup treated data as query text")
        before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS count")
        probe = store.put(
            json.dumps({"rollback_probe": root.model_dump()}).encode(),
            media_type="application/json",
        )
        driver.execute_query(
            "MATCH (a:FFArtifact {sha256:$sha}) SET a.size_bytes=a.size_bytes+1",
            sha=root.sha256,
        )
        rejected = False
        try:
            try:
                project_graph(probe, store, driver)
            except ValueError as error:
                if "transaction rolled back" not in str(error):
                    raise
                rejected = True
        finally:
            driver.execute_query(
                "MATCH (a:FFArtifact {sha256:$sha}) SET a.size_bytes=$size",
                sha=root.sha256,
                size=root.size_bytes,
            )
        after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS count")
        if not rejected or before[0]["count"] != after[0]["count"]:
            raise ValueError("Conflicting import left graph mutations")
        if related_research(probe.sha256, driver):
            raise ValueError("Rejected root remains discoverable")
        if project_graph(root, store, driver) != first:
            raise ValueError("Restored graph does not verify")
        version, _, _ = driver.execute_query(
            "CALL dbms.components() YIELD versions RETURN versions"
        )
        receipt = dict(
            server_versions=version[0]["versions"],
            research=first,
            synthetic_wrapper=second,
            related_roots=related,
            repeated_import_identical=True,
            parameter_binding_verified=True,
            conflict_rejected=True,
            rollback_verified=True,
            restored_readback_verified=True,
        )
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
