"""Verify a saved historical study's bytes, case inventory and actual SDK span identities."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path) -> dict[str, int]:
    """A complete manifest and exact Cartesian case inventory prevent selective result omission."""
    manifest = json.loads((root / "manifest.json").read_bytes())
    actual = {path.name for path in root.iterdir() if path.is_file()} - {"manifest.json"}
    if set(manifest) != actual:
        raise ValueError("Study manifest inventory differs")
    for name, digest in manifest.items():
        if (
            Path(name).name != name
            or hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Study artifact identity differs")
    freeze = json.loads((root / "freeze.json").read_bytes())
    report = json.loads((root / "report.json").read_bytes())
    expected = {(signal, cost) for signal in freeze["signals"] for cost in freeze["costs_bps"]}
    rows = report["experiments"]
    if len(rows) != len(expected) or {(r["signal"], r["cost_bps"]) for r in rows} != expected:
        raise ValueError("Experiment denominator differs")
    for row in rows:
        case = json.loads((root / f"{row['signal']}-{row['cost_bps']}.json").read_bytes())
        if case.get("summary", case) != row:
            raise ValueError("Case summary differs")
        if row["status"] == "completed" and len(case["periods"]) != row["n"]:
            raise ValueError("Case observation denominator differs")
    spans = [json.loads(line) for line in (root / "spans.jsonl").read_bytes().splitlines()]
    identities = {(s["context"]["trace_id"], s["context"]["span_id"]) for s in spans}
    if len(identities) != len(spans) or len(spans) != report["span_count"]:
        raise ValueError("Trace identities or counts differ")
    return dict(verified_files=len(manifest), experiments=len(rows), unique_spans=len(spans))


def main() -> None:
    """Inspect saved outputs only; verification never reruns model or experiment work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    print(json.dumps(verify(parser.parse_args().root)))


if __name__ == "__main__":
    main()
