"""Prepare an original two-signal composition example without reading expected backtest outputs."""

import json
from fractions import Fraction
from pathlib import Path

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.datasets import DatasetManifest
from factorforge.domain.raw_strategy import RawStrategySpec
from factorforge.domain.targets import Rational
from factorforge.factors.hybrid import HybridComponent, HybridRequest


def prepare_hybrid_fixture(repository: Path, store: ArtifactStore) -> HybridRequest:
    """Extend the original market fixture with independently authored competing quality scores."""
    fixture = repository / "data/backtests/monthly-raw-v1"
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        store.put((fixture / "inputs" / f"{name}.json").read_bytes(), media_type="application/json")
    signals = json.loads((fixture / "inputs/signals.json").read_bytes())
    for security, value in (("A", "1"), ("B", "3")):
        signals["facts"].append(
            dict(
                available_at="2024-04-30T12:00:00Z",
                concept="original-quality",
                period_end="2024-04-30",
                period_start=None,
                revision=0,
                security_id=security,
                source_id="quality-" + security,
                unit="dimensionless",
                value=value,
            )
        )
    signal_ref = store.put(
        json.dumps(signals, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/json",
    )
    manifest_wire = json.loads((fixture / "inputs/manifest.json").read_bytes())
    manifest_wire.update(name="original-hybrid-v1", source_version="hybrid-v1")
    for item in manifest_wire["objects"]:
        if item["name"] == "signals":
            item.update(
                artifact=signal_ref.model_dump(),
                row_count=len(signals["facts"]) + len(signals["membership"]),
            )
    manifest = DatasetManifest.model_validate_json(json.dumps(manifest_wire))
    manifest_ref = store.put(manifest.canonical_bytes(), media_type="application/json")
    parents = []
    for name, concept, text in (
        (
            "score",
            "original-score",
            "Original hypothesis one: rank by score, long high and short low. A=2, B=1.",
        ),
        (
            "quality",
            "original-quality",
            "Original hypothesis two: rank by quality, long high and short low. A=1, B=3.",
        ),
    ):
        wire = json.loads((fixture / "strategy.json").read_bytes())
        wire.update(factor_id="original-" + name, name="Original " + name, formula=name)
        wire["datasets"] = [
            dict(version_id=manifest_ref.sha256, manifest=manifest_ref.model_dump())
        ]
        for binding in (
            wire["universe"],
            wire["market"],
            *wire["signal_inputs"],
            wire["evaluation"]["benchmark"],
            wire["evaluation"]["risk_free"],
        ):
            binding["table"]["dataset_version"] = manifest_ref.sha256
            if binding["table"]["object_name"] == "signals":
                binding["table"]["artifact"] = signal_ref.model_dump()
        wire["signal_inputs"][0].update(name=name, concept=concept)
        wire["source_refs"].append(store.put(text.encode(), media_type="text/plain").model_dump())
        parents.append(RawStrategySpec.model_validate_json(json.dumps(wire)))
    return HybridRequest(
        name="Score and quality hybrid",
        rationale=(
            "Test a declared 75% score and 25% quality blend "
            "on two original fictional securities."
        ),
        components=tuple(
            HybridComponent(strategy=parent, weight=Rational.from_fraction(weight))
            for parent, weight in zip(parents, (Fraction(3, 4), Fraction(1, 4)), strict=True)
        ),
    )
