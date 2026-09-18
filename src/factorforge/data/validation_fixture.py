"""Author a separate twelve-return market fixture for executed time-series validation."""

import json
from itertools import pairwise
from pathlib import Path

from factorforge.data.artifacts import ArtifactStore
from factorforge.domain.datasets import DatasetManifest
from factorforge.domain.raw_strategy import RawStrategySpec


def prepare_validation_fixture(repository: Path, store: ArtifactStore) -> RawStrategySpec:
    """Retain distinct synthetic prices and rights without changing the original short fixture.

    Prices are authored inputs, not inferred from expected NAVs. The independent test
    computes the account path for ten shares per leg and the declared ten-basis-point cost.
    No real market-data coverage or published-factor reproduction is implied.
    """
    fixture = repository / "data/backtests/monthly-raw-v1"
    for name in ("calendar", "signals", "market", "intervals", "manifest", "input-freeze"):
        store.put((fixture / "inputs" / f"{name}.json").read_bytes(), media_type="application/json")
    calendar = json.loads((fixture / "inputs/calendar.json").read_bytes())
    sessions = [
        row for row in calendar["sessions"] if "2024-04-30" <= row["session_date"] <= "2024-05-16"
    ]
    prices = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110, 109, 112, 111]
    market = json.loads((fixture / "inputs/market.json").read_bytes())
    market["coverage_end"] = sessions[-1]["closes_at"]
    market["borrow_grants"][0]["valid_through"] = sessions[-1]["closes_at"]
    market["quotes"] = []
    for index, (session, price) in enumerate(zip(sessions, prices, strict=True)):
        for phase, clock in (("open", "opens_at"), ("close", "closes_at")):
            for security in ("A", "B"):
                value = (
                    100
                    if security == "B"
                    else (prices[max(0, index - 1)] if phase == "open" else price)
                )
                market["quotes"].append(
                    dict(
                        adjustment="unadjusted",
                        available_at=session[clock],
                        currency="USD",
                        observed_at=session[clock],
                        phase=phase,
                        price_usd=str(value),
                        security_id=security,
                        source_id=f"validation.{session['session_date']}.{phase}.{security}",
                    )
                )
    intervals = dict(
        schema_version="interval-returns-v1",
        rows=[
            dict(
                available_at=current["closes_at"],
                cumulative_return="0",
                end_at=current["closes_at"],
                series_id=series,
                source_id=f"validation.{series}.{current['session_date']}",
                start_at=previous["closes_at"],
            )
            for series in ("benchmark", "risk_free")
            for previous, current in pairwise(sessions)
        ],
    )
    refs = {
        name: store.put(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
            media_type="application/json",
        )
        for name, value in (("market", market), ("intervals", intervals))
    }
    manifest_wire = json.loads((fixture / "inputs/manifest.json").read_bytes())
    manifest_wire.update(
        name="original-validation-market-v1",
        source_version="validation-market-v1",
        coverage_end="2024-05-16",
    )
    for item in manifest_wire["objects"]:
        if item["name"] in refs:
            item.update(
                artifact=refs[item["name"]].model_dump(),
                row_count=len(market["quotes"]) + 1
                if item["name"] == "market"
                else len(intervals["rows"]),
            )
    manifest = DatasetManifest.model_validate_json(json.dumps(manifest_wire))
    manifest_ref = store.put(manifest.canonical_bytes(), media_type="application/json")
    wire = json.loads((fixture / "strategy.json").read_bytes())
    wire.update(factor_id="original-validation", name="Original twelve-return validation")
    wire["evaluation"]["sample_end"] = "2024-05-16"
    wire["datasets"] = [dict(version_id=manifest_ref.sha256, manifest=manifest_ref.model_dump())]
    for binding in (
        wire["universe"],
        wire["market"],
        *wire["signal_inputs"],
        wire["evaluation"]["benchmark"],
        wire["evaluation"]["risk_free"],
    ):
        table = binding["table"]
        table["dataset_version"] = manifest_ref.sha256
        if table["object_name"] in refs:
            table["artifact"] = refs[table["object_name"]].model_dump()
    return RawStrategySpec.model_validate_json(json.dumps(wire))
