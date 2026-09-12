"""Archive a verified historical study in local MLflow, without rerunning experiments."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from mlflow.tracking import MlflowClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.verify_historical_study import verify


def export_study(root: Path, database: Path, artifacts: Path) -> dict[str, object]:
    """Verify an immutable staging copy before logging; serial replay checks every byte."""
    database = database.resolve()
    artifacts = artifacts.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="factorforge-study-") as temporary:
        stage = Path(temporary)
        snapshot = stage / "study"
        snapshot.mkdir()
        paths = list(root.iterdir())
        if len(paths) > 128 or any(not p.is_file() or p.is_symlink() for p in paths):
            raise ValueError("Study must contain at most 128 regular files")
        for path in paths:
            with path.open("rb") as source:
                raw = source.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Study file exceeds 8 MiB")
            (snapshot / path.name).write_bytes(raw)
        counts = verify(snapshot)
        manifest = (snapshot / "manifest.json").read_bytes()
        identity = hashlib.sha256(manifest).hexdigest()
        report = json.loads((snapshot / "report.json").read_bytes())
        metrics = {name: float(value) for name, value in counts.items()}
        metrics["completed_experiments"] = float(
            sum(row["status"] == "completed" for row in report["experiments"])
        )
        metrics["source_rows"] = float(report["source_rows"])
        client = MlflowClient(tracking_uri="sqlite:///" + database.as_posix())
        experiment = client.get_experiment_by_name("FactorForge historical studies")
        if experiment is None:
            experiment_id = client.create_experiment(
                "FactorForge historical studies", artifact_location=artifacts.as_uri()
            )
        else:
            if experiment.artifact_location != artifacts.as_uri():
                raise ValueError("Existing experiment uses a different artifact location")
            experiment_id = experiment.experiment_id
        runs = client.search_runs(
            [experiment_id], filter_string=f"tags.study_sha256 = '{identity}'", max_results=2
        )
        if len(runs) > 1:
            raise ValueError("Duplicate study exports require inspection")
        if runs:
            run_id = runs[0].info.run_id
            if runs[0].info.status != "FINISHED":
                raise ValueError("Unfinished export requires inspection before retrying")
        else:
            run_id = client.create_run(
                experiment_id,
                tags={"study_sha256": identity, "scope": "historical_signal_cost_study"},
            ).info.run_id
            try:
                for name, value in metrics.items():
                    client.log_metric(run_id, name, value)
                client.log_artifacts(run_id, str(snapshot), artifact_path="study")
                client.set_terminated(run_id, "FINISHED")
            except BaseException:
                client.set_terminated(run_id, "FAILED")
                raise
        saved = client.get_run(run_id)
        if saved.data.metrics != metrics or saved.data.tags.get("study_sha256") != identity:
            raise ValueError("MLflow study metadata readback differs")
        destination = stage / "readback"
        destination.mkdir()
        downloaded = Path(client.download_artifacts(run_id, "study", str(destination)))
        if {p.name for p in downloaded.iterdir()} != {p.name for p in snapshot.iterdir()}:
            raise ValueError("MLflow study inventory readback differs")
        for path in snapshot.iterdir():
            if (downloaded / path.name).read_bytes() != path.read_bytes():
                raise ValueError("MLflow study artifact readback differs")
        return {
            "schema_version": "historical-study-mlflow-v1",
            "run_id": run_id,
            "study_sha256": identity,
            "metrics": metrics,
            "readback_files": len(paths),
            "artifact_readback_verified": True,
        }


def main() -> None:
    """Keep raw market inputs in explicit local storage and require a new receipt path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--tracking-artifacts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    with args.receipt.open("x", encoding="utf-8") as output:
        receipt = export_study(args.study, args.database, args.tracking_artifacts)
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
