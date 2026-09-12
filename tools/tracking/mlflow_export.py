"""Project verified research evidence into local MLflow without dispatching research work."""

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mlflow.tracking import MlflowClient

from factorforge.data.artifacts import LocalArtifactStore
from factorforge.lineage.closure import verify_closure
from factorforge.lineage.trajectories import TrajectoryRequest, export_trajectories


def export_tracking(
    request: TrajectoryRequest, store: LocalArtifactStore, database: Path, artifact_directory: Path
) -> dict[str, object]:
    """Export one serial projection; existing finished runs must reproduce the saved bytes."""
    projection = export_trajectories(request, store)
    manifest = projection.canonical_bytes()
    projection_ref = store.put(manifest, media_type="application/json")
    closure = verify_closure(projection_ref, store)
    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    artifact_directory = artifact_directory.resolve()
    artifact_directory.mkdir(parents=True, exist_ok=True)
    client = MlflowClient(tracking_uri="sqlite:///" + database.as_posix())
    experiment = client.get_experiment_by_name("FactorForge research evidence")
    if experiment is None:
        experiment_id = client.create_experiment(
            "FactorForge research evidence", artifact_location=artifact_directory.as_uri()
        )
    else:
        if experiment.artifact_location != artifact_directory.as_uri():
            raise ValueError("Existing experiment uses a different artifact location")
        experiment_id = experiment.experiment_id
    metrics = {
        "operations": float(projection.operation_count),
        "model_attempts": float(projection.model_attempt_count),
        "pending_operations": float(projection.pending_count),
        "missing_model_evidence": float(projection.missing_llm_evidence_count),
        "verified_objects": float(len(closure)),
        "verified_bytes": float(sum(ref.size_bytes for ref in closure)),
    }
    runs = client.search_runs(
        [experiment_id],
        filter_string=f"tags.projection_sha256 = '{projection_ref.sha256}'",
        max_results=2,
    )
    if len(runs) > 1:
        raise ValueError("Ambiguous duplicate tracking projections require inspection")
    if runs:
        run_id = runs[0].info.run_id
        if runs[0].info.status != "FINISHED":
            raise ValueError("An unfinished export exists; inspect it before retrying")
    else:
        run_id = client.create_run(
            experiment_id,
            tags={
                "projection_sha256": projection_ref.sha256,
                "source_sha256": request.source.sha256,
                "research_run_id": str(projection.run_id),
                "partition": request.partition,
                "training_eligibility": projection.training_eligibility,
                "scope": "evidence_projection",
            },
        ).info.run_id
        try:
            for name, value in metrics.items():
                client.log_metric(run_id, name, value)
            with TemporaryDirectory(prefix="factorforge-mlflow-") as directory:
                stage = Path(directory)
                (stage / "manifest.json").write_bytes(manifest)
                (stage / "trajectories.jsonl").write_bytes(store.get(projection.rows))
                objects = stage / "objects"
                objects.mkdir()
                for ref in closure:
                    (objects / ref.sha256).write_bytes(store.get(ref))
                client.log_artifacts(run_id, str(stage))
            client.set_terminated(run_id, "FINISHED")
        except BaseException:
            client.set_terminated(run_id, "FAILED")
            raise
    saved = client.get_run(run_id)
    if any(saved.data.metrics.get(name) != value for name, value in metrics.items()):
        raise ValueError("MLflow metric readback differs from verified evidence")
    with TemporaryDirectory(prefix="factorforge-mlflow-readback-") as directory:
        downloaded = Path(client.download_artifacts(run_id, "", directory))
        if (downloaded / "manifest.json").read_bytes() != manifest:
            raise ValueError("MLflow manifest readback differs")
        if (downloaded / "trajectories.jsonl").read_bytes() != store.get(projection.rows):
            raise ValueError("MLflow trajectory readback differs")
        for ref in closure:
            raw = (downloaded / "objects" / ref.sha256).read_bytes()
            if len(raw) != ref.size_bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
                raise ValueError("MLflow artifact readback differs")
    return {
        "schema_version": "mlflow-evidence-export-v1",
        "run_id": run_id,
        "projection": projection_ref.model_dump(),
        "metrics": metrics,
        "artifact_readback_verified": True,
    }


def main() -> None:
    """Restrict tracking to an explicit local SQLite database and local artifact directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--source-artifacts", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--tracking-artifacts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    with args.request.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Tracking request exceeds limit")
    with args.receipt.open("x", encoding="utf-8") as output:
        receipt = export_tracking(
            TrajectoryRequest.model_validate_json(raw),
            LocalArtifactStore(args.source_artifacts),
            args.database,
            args.tracking_artifacts,
        )
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
