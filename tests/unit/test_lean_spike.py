"""Original translation vectors do not claim that a LEAN strategy has run."""

import io
import json
from decimal import Inexact, localcontext
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile

import pytest

from infra.lean.spike import prepare

ROOT = Path(__file__).resolve().parents[2]


def module() -> ModuleType:
    """Return the repository-native translator without loading engine or strategy code."""
    return prepare


def source() -> bytes:
    """Original fixed prices are source inputs; this fixture contains no expected NAV."""
    return (ROOT / "infra/lean/spike/source.json").read_bytes()


def test_tick_translation_preserves_original_values_and_clocks() -> None:
    """Hand-declared CSV lines specify UTC milliseconds, scaled raw price and synthetic size."""
    files = module().build_files(source())
    for day, price in ("20240429", "1000000"), ("20240430", "1020000"), ("20240501", "1040000"):
        raw = files[f"data/equity/usa/tick/ffa/{day}_trade.zip"]
        with ZipFile(io.BytesIO(raw)) as archive:
            assert archive.namelist() == [f"{day}_ffa_Trade_Tick.csv"]
            assert archive.read(archive.namelist()[0]) == f"72000000,{price},1,,0,0\n".encode()
            assert archive.testzip() is None
    assert module().build_files(source()) == files
    assert files["source-original.json"] == source()
    assert all(b"nav_usd" not in raw for name, raw in files.items() if not name.endswith(".zip"))
    assert files["data/market-hours/market-hours-database.json"] == b'{"entries":{}}\n'


def test_tick_integer_scaling_ignores_hostile_decimal_context() -> None:
    """The fixed integer source cannot be rounded by unrelated process decimal settings."""
    expected = module().build_files(source())
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        assert module().build_files(source()) == expected


def test_original_fixture_uses_result_handler_without_spy_analysis() -> None:
    """Optional historical SPY analysis must not expand the original valuation data scope."""
    config = json.loads(module().build_files(source())["config.json"])
    assert config["result-handler"] == "FactorForge.LeanSpike.OriginalFixtureResultHandler"


@pytest.mark.parametrize(
    "change", ["price", "date", "cash", "quantity", "id", "extra", "duplicate"]
)
def test_spike_rejects_other_semantics_before_translation(change: str) -> None:
    """This first engine fixture does not silently broaden to the full gRPC input contract."""
    value = json.loads(source())
    if change == "price":
        value["snapshots"][0]["prices"][0]["price_usd"] = "100.00001"
    elif change == "date":
        value["snapshots"][0]["at"] = "2024-04-29T20:00:00.001Z"
    elif change == "cash":
        value["cash_usd"] = "1"
    elif change == "quantity":
        value["holdings"][0]["quantity"] = "11"
    elif change == "id":
        value["holdings"][0]["security_id"] = "../FFA"
    elif change == "extra":
        value["reference_nav"] = ["1000", "1020", "1040"]
    else:
        raw = source().replace(b'"cash_usd": "0"', b'"cash_usd":"1","cash_usd":"0"')
        with pytest.raises(ValueError):
            module().build_files(raw)
        return
    with pytest.raises(ValueError):
        module().build_files(json.dumps(value).encode())


@pytest.mark.parametrize("raw", [b"[]", b"{", b" " * 16385, b'{"cash_usd":NaN}'])
def test_source_byte_and_json_limits(raw: bytes) -> None:
    """Malformed and oversized sources fail before any file inventory can be generated."""
    with pytest.raises(ValueError):
        module().build_files(raw)


def test_config_is_local_csharp_and_excludes_credentials() -> None:
    """Handler selection and writable locations are fixed original controller choices."""
    files = module().build_files(source())
    config = json.loads(files["config.json"])
    assert config["live-mode"] is False and config["algorithm-language"] == "CSharp"
    assert config["algorithm-location"] == "/app/FactorForge.LeanSpike.dll"
    assert config["data-folder"] == "/input/data"
    assert config["data-provider"] == "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider"
    assert config["api-access-token"] == "" and config["python-venv"] == ""
    assert config["results-destination-folder"] == "/scratch/results"
    assert config["object-store-root"] == "/scratch/storage"
    assert config["security-data-feeds"] == {"Equity": ["Trade"]}
