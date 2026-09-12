"""Create SDK-validated LangSmith trace imports from verified research operation histories."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langsmith import Client
from langsmith.run_trees import RunTree

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.lineage.trajectories import TrajectoryRequest, export_trajectories

_FIELDS = {
    "id",
    "name",
    "run_type",
    "start_time",
    "end_time",
    "inputs",
    "outputs",
    "extra",
    "tags",
    "trace_id",
    "parent_run_id",
    "dotted_order",
}


def make_runs(
    rows: list[dict[str, Any]], projection_sha256: str, project: str
) -> list[dict[str, Any]]:
    """Construct one trace root and one child per actual operation, using recorded timestamps."""
    if not rows or len(rows) > 1000 or not project.strip() or len(project) > 128:
        raise ValueError("Trace import requires a bounded nonempty operation history and project")
    start = min(datetime.fromisoformat(row["reserved_at"]) for row in rows)
    end = (
        max(datetime.fromisoformat(row["settled_at"]) for row in rows)
        if all(row["settled_at"] for row in rows)
        else None
    )
    parent = RunTree(
        id=uuid5(NAMESPACE_URL, project + ":" + projection_sha256),
        name="FactorForge retained research",
        run_type="chain",
        start_time=start,
        end_time=end,
        project_name=project,
        inputs={"projection_sha256": projection_sha256},
        outputs={"recorded_operations": len(rows)},
        tags=["factorforge", "retrospective"],
        extra={"metadata": {"origin": "verified-operation-ledger", "live_instrumentation": False}},
    )
    result = [parent.model_dump(mode="json", include=_FIELDS)]
    for row in rows:
        child = RunTree(
            id=uuid5(parent.id, row["operation_id"]),
            name="FactorForge " + row["kind"],
            run_type="llm" if row["kind"] == "llm" else "tool",
            project_name=project,
            parent_run=parent,
            start_time=datetime.fromisoformat(row["reserved_at"]),
            end_time=datetime.fromisoformat(row["settled_at"]) if row["settled_at"] else None,
            inputs={"operation_id": row["operation_id"], "sequence": row["sequence"]},
            outputs={
                key: row.get(key) for key in ("operation_status", "root_status", "decision_status")
            },
            tags=["factorforge", "retrospective"],
            extra={
                "metadata": {
                    "projection_sha256": projection_sha256,
                    "retained_model_attempts": len(row["model_attempts"]),
                    "timing_scope": "operation-reservation-to-settlement",
                }
            },
        )
        result.append(child.model_dump(mode="json", include=_FIELDS))
    return result


def upload_runs(runs: list[dict[str, Any]], project: str, client: Client) -> None:
    """Upload only allowlisted metadata; stable IDs support server-side trace identity."""
    for run in runs:
        client.create_run(**run, project_name=project)
    client.flush(timeout=30)


def main() -> None:
    """Build a local bundle; explicit --upload enables configured LangSmith I/O."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", default="factorforge-retained-evidence")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Trace request exceeds limit")
    store = LocalArtifactStore(args.artifacts)
    with args.output.open("x", encoding="utf-8") as output:
        projection = export_trajectories(TrajectoryRequest.model_validate_json(raw), store)
        ref = store.put(projection.canonical_bytes(), media_type="application/json")
        rows = [json.loads(line) for line in store.get(projection.rows).splitlines()]
        runs = make_runs(rows, ref.sha256, args.project)
        bundle = {
            "schema_version": "langsmith-retrospective-v1",
            "project": args.project,
            "projection": ref.model_dump(),
            "runs": runs,
        }
        json.dump(bundle, output, indent=2)
    if args.upload:
        client = Client(auto_batch_tracing=False)
        upload_runs(runs, args.project, client)
    print(
        json.dumps(
            {
                "trace_records": len(runs),
                "operations": len(rows),
                "upload_requested": args.upload,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
