"""Exercise real SQLite MLflow export, serial replay and corruption detection."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from historical_export import export_study


def check(study: Path, root: Path) -> dict[str, object]:
    """Use disposable copies so corruption probes cannot modify original evidence."""
    source = root / "source"
    shutil.copytree(study, source)
    database, artifacts = root / "tracking.db", root / "artifacts"
    first = export_study(source, database, artifacts)
    assert export_study(source, database, artifacts) == first
    stored = list(artifacts.rglob("report.json"))
    assert len(stored) == 1
    original = stored[0].read_bytes()
    stored[0].write_bytes(original + b" ")
    try:
        export_study(source, database, artifacts)
    except ValueError as error:
        assert "artifact readback differs" in str(error)
    else:
        raise AssertionError("Tracking corruption was accepted")
    stored[0].write_bytes(original)
    assert export_study(source, database, artifacts) == first
    (source / "report.json").write_bytes(original + b" ")
    try:
        export_study(source, database, artifacts)
    except ValueError as error:
        assert "artifact identity differs" in str(error)
    else:
        raise AssertionError("Source corruption was accepted")
    return {"export": first, "serial_replay": True, "corruption_checks": 2}


def main() -> None:
    """Require an operator-owned study; raw data never leaves local temporary storage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.workspace is not None:
        print(json.dumps(check(args.study, args.workspace)))
        return
    # MLflow caches database connections; exit the worker before Windows cleanup.
    with TemporaryDirectory(prefix="factorforge-tracking-check-") as temporary:
        subprocess.run(
            [sys.executable, __file__, str(args.study), "--workspace", temporary], check=True
        )


if __name__ == "__main__":
    main()
