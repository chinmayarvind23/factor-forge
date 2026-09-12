"""Translate the original twelve-return source inputs into a separate LEAN execution trial."""

import hashlib
import io
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from factorforge.data.artifacts import ArtifactStore, verify_bytes
from factorforge.data.validation_fixture import prepare_validation_fixture
from infra.lean.spike.prepare import build_files as seeded_files


def build_files(repository: Path, artifacts: ArtifactStore) -> dict[str, bytes]:
    """Stage only original strategy, raw market and signals; no Python execution is invoked."""
    spec = prepare_validation_fixture(repository, artifacts)
    inputs = {}
    for name, ref in (
        ("market", spec.market.table.artifact),
        ("signals", spec.universe.table.artifact),
    ):
        raw = artifacts.get(ref)
        verify_bytes(raw, ref)
        inputs[name] = json.loads(raw)
    base = seeded_files((repository / "infra/lean/spike/source.json").read_bytes())
    files = {
        name: base[name]
        for name in (
            "data/market-hours/market-hours-database.json",
            "data/symbol-properties/symbol-properties-database.csv",
        )
    }
    source = dict(
        schema_version="original-lean-execution-v1",
        initial_cash_usd="1002",
        strategy=spec.model_dump(mode="json"),
        **inputs,
    )
    files["source.json"] = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    for security, ticker in (("A", "ffa"), ("B", "ffb")):
        files[f"data/equity/usa/map_files/{ticker}.csv"] = (
            f"19980101,{ticker}\n20501231,{ticker}\n".encode()
        )
        files[f"data/equity/usa/factor_files/{ticker}.csv"] = b"19980101,1,1,0\n20501231,1,1,0\n"
        days: dict[str, list[str]] = {}
        for row in inputs["market"]["quotes"]:
            if row["security_id"] != security:
                continue
            at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
            milliseconds = (at.hour * 3600 + at.minute * 60 + at.second) * 1000
            scaled = Decimal(row["price_usd"]) * 10000
            days.setdefault(at.strftime("%Y%m%d"), []).append(f"{milliseconds},{scaled},1,,0,0\n")
        # The synthetic always-open reader asks for every date; empty files declare no ticks.
        day_at = datetime.strptime(min(days), "%Y%m%d")
        last_day = datetime.strptime(max(days), "%Y%m%d")
        while day_at <= last_day:
            days.setdefault(day_at.strftime("%Y%m%d"), [])
            day_at += timedelta(days=1)
        for day, rows in sorted(days.items()):
            output = io.BytesIO()
            with ZipFile(output, "w", compression=ZIP_STORED) as archive:
                entry = ZipInfo(f"{day}_{ticker}_Trade_Tick.csv", (2024, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100444 << 16
                archive.writestr(entry, "".join(rows).encode())
            files[f"data/equity/usa/tick/{ticker}/{day}_trade.zip"] = output.getvalue()
    config = json.loads(base["config.json"])
    config.update(
        {
            "algorithm-type-name": "FactorForge.LeanExecution.ExecutedEquityAlgorithm",
            "result-handler": "FactorForge.LeanExecution.OriginalFixtureResultHandler",
            "symbol-tick-limit": 2,
        }
    )
    files["config.json"] = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    files["input-manifest.json"] = json.dumps(
        dict(
            schema_version="original-lean-execution-files-v1",
            files=[
                dict(path=name, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                for name, raw in sorted(files.items())
            ],
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return files
