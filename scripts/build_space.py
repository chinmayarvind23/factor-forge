"""Build a public evidence demo from fresh executions of the original monthly fixture."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from factorforge.backtests.monthly import run_monthly
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.lineage.closure import verify_closure

REPO = Path(__file__).resolve().parents[1]


def build(output: Path) -> None:
    """Publish only original fixture evidence; private runs and credentials are never inputs."""
    output.mkdir(parents=True, exist_ok=True)
    store = LocalArtifactStore(output / "objects")
    fixture = REPO / "data/backtests/monthly-raw-v1"
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        store.put((fixture / "inputs" / f"{name}.json").read_bytes(), media_type="application/json")
    spec = RawStrategySpec.model_validate_json((fixture / "strategy.json").read_bytes())
    cases = []
    for key, title, capital in (
        ("completed", "A complete monthly experiment", "1002"),
        ("precision", "An execution guard in action", "1000"),
    ):
        result = run_monthly(
            spec,
            store,
            initial_cash_usd=Decimal(capital),
            evaluated_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        )
        root = store.put(result.canonical_bytes(), media_type="application/json")
        refs = verify_closure(root, store)
        cases.append(
            dict(
                id=key,
                title=title,
                root=root.model_dump(),
                objects=len(refs),
            )
        )
    manifest = dict(
        schema_version="factorforge-public-demo-v1",
        scope=(
            "Original synthetic fixture executions. Saved evidence, not live model inference "
            "or published-factor replication."
        ),
        cases=cases,
    )
    (output / "evidence.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name in ("index.html", "app.js", "style.css", "README.md"):
        shutil.copyfile(REPO / "apps/demo" / name, output / name)
    print(
        json.dumps(
            {
                "output": str(output),
                "cases": len(cases),
                "objects": sum(c["objects"] for c in cases),
            }
        )
    )


def main() -> None:
    """Keep publication separate from building so the exact public directory is reviewable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "dist/space")
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()
