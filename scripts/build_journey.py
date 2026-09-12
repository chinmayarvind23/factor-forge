"""Build a public walkthrough from one verified, retained original research run."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from factorforge.data.artifacts import LocalArtifactStore, verify_bytes
from factorforge.domain.artifacts import ArtifactRef
from factorforge.lineage.closure import verify_closure


def build(run: Path, reference_demo: Path, output: Path) -> None:
    """Extract display fields only after closure verification; never rerun or amend a model."""
    store = LocalArtifactStore(run / "objects")
    inspection = json.loads((run / "inspection.json").read_bytes())
    root = ArtifactRef.model_validate(inspection["result"])
    closure = verify_closure(root, store)

    def read(ref: dict[str, Any]) -> dict[str, Any]:
        """Verify each retained object against its full content reference before decoding."""
        identity = ArtifactRef.model_validate(ref)
        raw = store.get(identity)
        verify_bytes(raw, identity)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected a retained JSON object")
        return value

    result = read(root.model_dump())
    request = json.loads((run / "request.json").read_bytes())
    if request["plan"] != result["plan"]:
        raise ValueError("Request plan differs from the retained scheduler")
    if len(result["plan"]["catalog"]["entries"]) != 1:
        raise ValueError("Walkthrough requires the original single-source case")
    entry = result["plan"]["catalog"]["entries"][0]
    if entry["document"]["paper_id"] != "original-monthly-v1":
        raise ValueError("Only the authored public integration source may be exported")
    if (
        hashlib.sha256(entry["document"]["text"].encode()).hexdigest()
        != entry["document"]["source_sha256"]
    ):
        raise ValueError("Displayed passage differs from its source identity")
    strategies = read(result["strategies"])
    candidate = strategies["candidates"][0]["draft"]["strategy"]
    extraction_ref = inspection["extractions"][0]["record"]
    extraction = read(extraction_ref)
    observation = read(extraction["observation"])
    provider = read(extraction["provider_record"])
    monthly_ref = result["experiments"][0]["result"]
    monthly = read(monthly_ref)
    if candidate != monthly["request"]["spec"]:
        raise ValueError("Displayed strategy differs from the actual attempted experiment")
    reference_manifest = json.loads((reference_demo / "evidence.json").read_bytes())
    reference_ref = next(
        row["root"] for row in reference_manifest["cases"] if row["id"] == "completed"
    )
    ref_store = LocalArtifactStore(reference_demo / "objects")
    reference_id = ArtifactRef.model_validate(reference_ref)
    verify_closure(reference_id, ref_store)
    reference_raw = ref_store.get(reference_id)
    verify_bytes(reference_raw, reference_id)
    baseline = json.loads(reference_raw)
    if (
        baseline["status"] != "completed"
        or monthly["failure_code"] != "MONTHLY_BORROW_UNAVAILABLE_OR_AMBIGUOUS"
    ):
        raise ValueError("Walkthrough evidence does not match its declared narrative")
    data = {
        "schema_version": "research-journey-v1",
        "scope": (
            "Replay of a recorded local model run on an authored integration fixture. "
            "No live inference."
        ),
        "run_id": result["run_id"],
        "idea": request["brief"]["idea"],
        "budget": request["brief"],
        "document": entry["document"],
        "observation": observation,
        "provider": {
            key: provider[key] for key in ("model", "prompt_tokens", "output_tokens", "wall_ms")
        },
        "strategy": {
            "formula": candidate["formula"],
            "timing": candidate["timing"],
            "direction": candidate["portfolio"]["allocation"]["direction"],
            "costs": candidate["costs"],
        },
        "execution": {
            "status": monthly["status"],
            "reason": monthly["failure_code"],
            "fills": len(monthly["fills"]),
            "observations": len(monthly["observations"]),
            "initial_cash": monthly["request"]["initial_cash_usd"],
        },
        "evidence": {
            "scheduler": root.model_dump(),
            "extraction": extraction_ref,
            "monthly": monthly_ref,
            "verified_objects": len(closure),
        },
        "reference": {
            "scope": "Separately authored deterministic reference; not a correction by the agent.",
            "root": reference_ref,
            "fills": len(baseline["fills"]),
            "terminal_nav": baseline["observations"][-1]["snapshot"]["nav_usd"],
            "initial_cash": baseline["request"]["initial_cash_usd"],
            "direction": baseline["request"]["spec"]["portfolio"]["allocation"]["direction"],
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, indent=2) + "\n").encode()
    output.write_bytes(raw)
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "verified_objects": len(closure),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reference-demo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.run, args.reference_demo, args.output)
