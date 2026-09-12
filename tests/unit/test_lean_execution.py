"""Original execution translation supplies prices and signals, never Python fills or NAV."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

from test_monthly_admission import MemoryStore

from infra.lean.execution.prepare import build_files


def test_execution_input_has_two_raw_equities_and_no_reference_answers() -> None:
    """Tick prices and clocks are independently asserted at entry and liquidation."""
    files = build_files(Path(__file__).resolve().parents[2], MemoryStore())
    source = json.loads(files["source.json"])
    assert source["initial_cash_usd"] == "1002"
    assert "fills" not in source and "performance" not in source
    assert b"terminal_nav_usd" not in files["source.json"]
    assert len([name for name in files if name.endswith(".zip")]) == 34
    for day, ticker, expected in [
        ("20240501", "ffa", b"48600000,1000000,1,,0,0\n72000000,1020000,1,,0,0\n"),
        ("20240516", "ffb", b"48600000,1000000,1,,0,0\n72000000,1000000,1,,0,0\n"),
        ("20240504", "ffa", b""),
    ]:
        with ZipFile(
            io.BytesIO(files[f"data/equity/usa/tick/{ticker}/{day}_trade.zip"])
        ) as archive:
            assert archive.read(archive.namelist()[0]) == expected
    assert build_files(Path(__file__).resolve().parents[2], MemoryStore()) == files
