"""Translate only one original equity fixture; no engine execution or NAV calculation."""

import hashlib
import io
import json
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from factorforge.interop.lean.contract import PriceOnlySource

CLOCKS = ("2024-04-29T20:00:00Z", "2024-04-30T20:00:00Z", "2024-05-01T20:00:00Z")
PRICES = ("100", "102", "104")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Duplicate source keys cannot select different values in Python and .NET readers."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate source field")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    """Nonfinite JSON extensions are outside the original fixture contract."""
    raise ValueError("Nonfinite source value")


def _encode(value: object) -> bytes:
    """Stable JSON supplies exact original bytes for the later controller inventory."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def build_files(raw: bytes) -> dict[str, bytes]:
    """Produce a fixed safe path inventory; the caller owns staging and exclusive publication.

    This pure function supports the declared three-row engineering fixture only. The broader
    gRPC source schema does not imply that this spike can execute all of its valid inputs.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= 16384:
        raise ValueError("Source exceeds spike bound")
    try:
        json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        source = PriceOnlySource.model_validate_json(raw, strict=True)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Invalid spike source") from None
    if (
        source.cash_usd != "0"
        or len(source.holdings) != 1
        or source.holdings[0].security_id != "SEC-A"
        or source.holdings[0].quantity != "10"
        or source.holdings[0].average_price_usd != "100"
        or tuple(row.at for row in source.snapshots) != CLOCKS
        or tuple(row.prices[0].price_usd for row in source.snapshots) != PRICES
    ):
        raise ValueError("Source is outside the original equity tick spike")
    files = {
        "source-original.json": raw,
        "source.json": source.canonical_bytes(),
        "data/market-hours/market-hours-database.json": b'{"entries":{}}\n',
        "data/symbol-properties/symbol-properties-database.csv": (
            b"market,symbol,security-type,description,quote-currency,contract-multiplier,"
            b"minimum-price-variation,lot-size,market-ticker\n"
        ),
        "data/equity/usa/map_files/ffa.csv": b"19980101,ffa\n20501231,ffa\n",
        "data/equity/usa/factor_files/ffa.csv": b"19980101,1,1,0\n20501231,1,1,0\n",
    }
    for snapshot in source.snapshots:
        day = snapshot.at[:10].replace("-", "")
        # These three original UTC instants are all exactly 20 hours after midnight.
        price = int(snapshot.prices[0].price_usd) * 10000
        content = f"72000000,{price},1,,0,0\n".encode()
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            entry = ZipInfo(f"{day}_ffa_Trade_Tick.csv", (2024, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_STORED
            entry.create_system = 3
            entry.external_attr = 0o100444 << 16
            archive.writestr(entry, content)
        files[f"data/equity/usa/tick/ffa/{day}_trade.zip"] = output.getvalue()
    files["config.json"] = _encode(
        {
            "live-mode": False,
            "algorithm-type-name": "FactorForge.LeanSpike.SeededEquityAlgorithm",
            "algorithm-language": "CSharp",
            "algorithm-location": "/app/FactorForge.LeanSpike.dll",
            "composer-dll-directory": "/app",
            "data-folder": "/input/data",
            "results-destination-folder": "/scratch/results",
            "object-store-root": "/scratch/storage",
            "log-handler": "QuantConnect.Logging.ConsoleLogHandler",
            "messaging-handler": "QuantConnect.Messaging.Messaging",
            "job-queue-handler": "QuantConnect.Queues.JobQueue",
            "api-handler": "QuantConnect.Api.Api",
            "lean-manager-type": "LocalLeanManager",
            "map-file-provider": "LocalDiskMapFileProvider",
            "factor-file-provider": "LocalDiskFactorFileProvider",
            "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
            "data-permission-manager": "DataPermissionManager",
            "setup-handler": "BacktestingSetupHandler",
            "result-handler": "FactorForge.LeanSpike.OriginalFixtureResultHandler",
            "data-feed-handler": "FileSystemDataFeed",
            "real-time-handler": "BacktestingRealTimeHandler",
            "transaction-handler": "BacktestingTransactionHandler",
            "history-provider": "SubscriptionDataReaderHistoryProvider",
            "object-store": "LocalObjectStore",
            "job-user-id": "0",
            "api-access-token": "",
            "job-organization-id": "",
            "python-venv": "",
            "debugging": False,
            "debug-mode": False,
            "close-automatically": True,
            "show-missing-data-logs": True,
            "symbol-minute-limit": 1,
            "symbol-second-limit": 1,
            "symbol-tick-limit": 1,
            "security-data-feeds": {"Equity": ["Trade"]},
            "maximum-data-points-per-chart-series": 128,
            "maximum-chart-series": 8,
        }
    )
    files["input-manifest.json"] = _encode(
        {
            "schema_version": "original-equity-tick-spike-v1",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "clock": "original-always-open-UTC",
            "synthetic_tick_quantity": "1",
            "files": [
                {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                for path, data in sorted(files.items())
            ],
        }
    )
    return files
